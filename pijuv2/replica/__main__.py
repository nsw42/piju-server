from argparse import ArgumentParser
from contextlib import nullcontext
from http import HTTPStatus
import json
import os
from pathlib import Path
from typing import List, Optional
import urllib.parse

from flask import abort, Blueprint, Flask, has_app_context, redirect, request
from flask_sock import Sock, ConnectionClosed
import requests

from pijuv2.backend.routeconsts import RouteConstants

from ..backend.downloadinfo import DownloadInfo
from ..backend.deserialize import extract_id
from ..backend.routes import gzippable_jsonify, make_options_response
from ..player.fileplayer import FilePlayer
from ..player.streamplayer import StreamPlayer


APP_NOT_INIT_ERROR = "App not initialised"

REQUEST_TIMEOUT = 300  # timeout, in seconds, for requests.get()


# Replica App -------------------------------------------------------------------------------------

class ReplicaApp(Flask):
    def __init__(self, resolved_cache_path: Path, primary: str):
        super().__init__(__name__)
        self.cache_path = resolved_cache_path
        self.primary = primary
        self.file_player = FilePlayer()
        self.stream_player = StreamPlayer()
        self.current_player = self.file_player
        self.api_version_string = '7.0'
        self.current_track_info = None  # a cache of http://primary/tracks/trackid
        self.current_track_id = None  # id for current_track_info
        self.websocket_clients = []

        def state_change_callback():
            self.update_now_playing()
        self.file_player.set_state_change_callback(state_change_callback)
        self.stream_player.set_state_change_callback(state_change_callback)

    def fetch_track_info(self, trackid):
        response = requests.get(f'{self.primary}/tracks/{trackid}', timeout=REQUEST_TIMEOUT)
        if not response.ok:
            return None
        self.current_track_id = trackid
        self.current_track_info = response.json()

    def update_now_playing(self):
        context_manager = nullcontext if has_app_context() else self.app_context
        with context_manager():
            data = json.dumps(get_current_status())
            for ws in self.websocket_clients[:]:
                try:
                    ws.send(data)
                except ConnectionClosed:
                    self.websocket_clients.remove(ws)


app: Optional[ReplicaApp] = None

# ROUTES ------------------------------------------------------------------------------------------

routes = Blueprint('routes', __name__, url_prefix='')
sock = Sock()


def add_query_string_to_redirect(redirect_to):
    if request.query_string:
        redirect_to += '?' + request.query_string.decode('utf-8')
    return redirect(redirect_to)


@routes.after_request
def add_security_headers(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


@routes.route("/")
def current_status():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    rtn = get_current_status()

    return gzippable_jsonify(rtn)


def get_current_status():
    assert app
    c_p = app.current_player
    rtn = {
        'WorkerStatus': 'Idle',
        'PlayerStatus': c_p.current_status,
        'PlayerVolume': c_p.current_volume,
        'CurrentTrackIndex': None if (c_p.current_track_index is None) else (c_p.current_track_index + 1),
        'MaximumTrackIndex': c_p.number_of_tracks,
        'ApiVersion': app.api_version_string,
    }
    if c_p == app.file_player:
        rtn['CurrentTracklistUri'] = c_p.current_tracklist_identifier
        if c_p.current_track:
            if c_p.current_track.trackid != app.current_track_id:
                app.fetch_track_info(c_p.current_track.trackid)

            rtn['CurrentTrack'] = app.current_track_info
            rtn['CurrentArtwork'] = app.current_track_info['artwork'] if app.current_track_info else None

    return rtn


@routes.get(RouteConstants.ONE_ALBUM)
def get_album(albumid):
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    return add_query_string_to_redirect(f'{app.primary}/albums/{albumid}')


@routes.get(RouteConstants.GET_ARTIST)
def get_artist(artist):
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    return add_query_string_to_redirect(f'{app.primary}/artists/{artist}')


@routes.get(RouteConstants.GET_ARTWORK)
def get_artwork(artworkid):
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    return redirect(f'{app.primary}/artwork/{artworkid}')


@routes.route("/cache/<int:trackid>")
def cache(trackid):
    tracks = get_tracks_for_single_track(trackid)
    ensure_cache_exists(tracks)
    return ('', HTTPStatus.NO_CONTENT)


@routes.get("/genres")
def get_all_genres():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    return redirect(app.primary + '/genres')


@routes.get(RouteConstants.GET_GENRE)
def get_genre(genreid):
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    redirect_to = f'{app.primary}/genres/{genreid}'
    if request.query_string:
        redirect_to += '?' + request.query_string.decode('utf-8')
    return redirect(redirect_to)


@routes.route("/player/next", methods=['POST'])
def update_player_next():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)

    app.current_player.next()
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/pause", methods=['POST'])
def update_player_pause():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)

    app.current_player.pause()
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/play", methods=['POST'])
def update_player_play():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)

    data = request.get_json()
    if not data:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')

    albumid = extract_id(data.get('album'))
    playlistid = extract_id(data.get('playlist'))
    queue_pos = extract_id(data.get('queuepos'))
    trackid = extract_id(data.get('track'))
    radioid = extract_id(data.get('radio'))
    disk_nr = data.get('disk')
    if disk_nr:
        disk_nr = int(disk_nr)
    youtubeurl = data.get('url')

    # Valid requests (per the API, but not necessary supported in the replica app):
    #   album with at most one of track or disk number
    #   playlist with or without track
    #   queuepos with or without track
    #   track on its own
    #   youtubeurl (with nothing else) - not yet supported in the replica app
    #   radio (with nothing else) - not yet supported in the replica app

    if not any([albumid, playlistid, queue_pos, trackid, radioid, youtubeurl]):
        abort(HTTPStatus.BAD_REQUEST, description='Something to play must be specified')

    if sum(x is not None for x in [albumid, playlistid, queue_pos]) > 1:
        abort(HTTPStatus.BAD_REQUEST, description="At most one of album, playlist and queuepos may be specified")

    if youtubeurl:
        abort(HTTPStatus.BAD_REQUEST, description="Play from YouTube not yet supported in the replica app")

    if radioid:
        abort(HTTPStatus.BAD_REQUEST, description="Play from radio not yet supported in the replica app")

    if albumid is not None:
        play_album(albumid, trackid, disk_nr)

    elif playlistid is not None:
        play_playlist(playlistid, trackid)

    elif queue_pos is not None:
        # We're moving within the queue: the cached versions should already exist
        if not app.current_player.play_from_apparent_queue_index(queue_pos, trackid=trackid):
            abort(HTTPStatus.CONFLICT, "Track index not found")

    elif trackid:
        play_track(trackid)

    else:
        abort(HTTPStatus.BAD_REQUEST, description='Album, playlist or track must be specified')

    return ('', HTTPStatus.NO_CONTENT)


def play_album(albumid: int, trackid: int | None, disk_nr: int | None):
    assert app
    tracks = get_tracks_for_album(albumid, disk_nr)
    play_track_list(tracks, '/albums/' + str(albumid), trackid)


def get_tracks_for_album(albumid: int, disk_nr: int | None) -> List[DownloadInfo]:
    assert app
    response = requests.get(f'{app.primary}/albums/{albumid}?tracks=all', timeout=REQUEST_TIMEOUT)
    if not response.ok:
        abort(HTTPStatus.NOT_FOUND, description="Unknown album id")

    tracks = response.json()['tracks']
    if disk_nr is not None:
        tracks = [track for track in tracks if track['disknumber'] == disk_nr]

    return download_info_list_from_api_list_of_tracks(tracks)


def get_tracks_for_playlist(playlistid: int) -> List[DownloadInfo]:
    assert app
    response = requests.get(f'{app.primary}/playlists/{playlistid}?tracks=all', timeout=REQUEST_TIMEOUT)
    if not response.ok:
        abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
    tracks = response.json()['tracks']
    return download_info_list_from_api_list_of_tracks(tracks)


def get_tracks_for_single_track(trackid: int) -> List[DownloadInfo]:
    assert app
    response = requests.get(f'{app.primary}/tracks/{trackid}', timeout=REQUEST_TIMEOUT)
    if not response.ok:
        abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
    return download_info_list_from_api_list_of_tracks([response.json()])


def download_info_list_from_api_list_of_tracks(tracks: List[dict]) -> List[DownloadInfo]:
    assert app
    rtn = []
    for track in tracks:
        track_id = extract_id(track['link'])
        if track_id:
            rtn.append(DownloadInfo(filepath=cache_path(track_id),
                                    artist=track['artist'],
                                    title=track['title'],
                                    artwork=app.primary + track['artwork'] if track['artwork'] else None,
                                    url='',
                                    fake_trackid=track_id))
    return rtn


def play_playlist(playlistid: int, trackid: int | None):
    assert app
    tracks = get_tracks_for_playlist(playlistid)
    play_track_list(tracks, '/playlists/' + str(playlistid), trackid)


def play_track(trackid: int):
    assert app
    tracks = get_tracks_for_single_track(trackid)
    play_track_list(tracks, None, trackid)  # There is no tracklist URI when we're playing a single track


@routes.post("/player/previous")
def update_player_prev():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)

    app.current_player.prev()
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/resume")
def update_player_resume():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)

    app.current_player.resume()
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/stop")
def update_player_stop():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)

    app.current_player.stop()
    return ('', HTTPStatus.NO_CONTENT)


@routes.get("/player/volume")
def player_get_volume():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)

    return {"volume": app.current_player.current_volume}


@routes.post("/player/volume")
def player_set_volume():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    data = request.get_json()
    if not data:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    try:
        volume = data.get('volume')
        volume = int(volume)
        for player in (app.file_player, app.stream_player):
            player.set_volume(volume)
        return ('', HTTPStatus.NO_CONTENT)
    except (AttributeError, KeyError, ValueError):
        abort(HTTPStatus.BAD_REQUEST, description='Volume must be specified and numeric')


@routes.get("/playlists/")
def get_playlists():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    return redirect(f'{app.primary}/playlists')


@routes.delete("/queue/", provide_automatic_options=False)
def queue_delete():
    abort(HTTPStatus.NOT_IMPLEMENTED, "Not yet implemented")


@routes.get("/queue/", provide_automatic_options=False)
def queue_get():
    abort(HTTPStatus.NOT_IMPLEMENTED, "Not yet implemented")


@routes.route("/queue/", methods=['OPTIONS'], provide_automatic_options=False)
def queue_options():
    # the request to add to queue looks like a cross-domain request to Chrome,
    # so it sends OPTIONS before the PUT. Hence we need to support this.
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)

    # TODO
    # if app.current_player != app.file_player:
    #     select_player(app, app.file_player)

    return make_options_response(['DELETE', 'GET', 'OPTIONS', 'PUT'])


@routes.put("/queue/", provide_automatic_options=False)
def queue_put():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    data = request.get_json()
    if not data:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')

    # there are five different possibilities here:
    #   album: albumid  disk: disknr  # add the tracks from the given disk to queue
    #   album: albumid                # add the given album to queue
    #   track: trackid                # add the given track to queue
    #   url: url                      # add the audio from the given URL to queue
    #   queue: [trackid_or_url]       # reorder the queue
    if albumid := extract_id(data.get('album', '')):
        disknr = extract_id(data.get('disk', ''))
        return queue_put_album(albumid, disknr)

    if trackid := extract_id(data.get('track', '')):
        return queue_put_track(trackid)

    if data.get('url'):
        abort(HTTPStatus.NOT_IMPLEMENTED, "Fetching from YouTube not currently implemented in the replica player")

    if new_queue_order := data.get('queue'):
        return queue_put_reorder(new_queue_order)

    abort(HTTPStatus.BAD_REQUEST, description="No album+disk id, track id, url or new queue order specified")


def queue_put_album(albumid: int, disk_nr: int | None):
    tracks = get_tracks_for_album(albumid, disk_nr)
    ensure_cache_exists(tracks)
    add_tracks_to_current_player_queue(tracks)
    return ('', HTTPStatus.NO_CONTENT)


def queue_put_reorder(new_queue_order: List[int]):
    assert app
    new_queue = []
    for track_id in new_queue_order:
        tracks = get_tracks_for_single_track(track_id)
        new_queue.append(tracks[0])
    app.current_player.set_queue(new_queue, "/queue")
    return ('', HTTPStatus.NO_CONTENT)


def queue_put_track(trackid):
    tracks = get_tracks_for_single_track(trackid)
    ensure_cache_exists(tracks)
    add_tracks_to_current_player_queue(tracks)
    return ('', HTTPStatus.NO_CONTENT)


def add_tracks_to_current_player_queue(tracks: List[DownloadInfo]):
    assert app
    for track in tracks:
        app.current_player.add_to_queue(str(track.filepath),
                                        track.fake_trackid,
                                        track.artist,
                                        track.title,
                                        track.artwork)


@routes.get("/radio")
def get_readio_stations():
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    return redirect(f'{app.primary}/radio')


@routes.get("/search/<search_string>")
def search(search_string):
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    return add_query_string_to_redirect(f'{app.primary}/search/{search_string}')


@sock.route('/ws', routes)
def websocket_client(ws):
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    if sock.app:
        sock.app.websocket_clients.append(ws)
    data = get_current_status()
    ws.send(json.dumps(data))
    while True:
        _ = ws.receive()


# APPLICATION -------------------------------------------------------------------------------------

def cache_path(track_id) -> Path:
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    info = requests.get(f'{app.primary}/tracks/{track_id}', timeout=REQUEST_TIMEOUT)
    if not info.ok:
        abort(HTTPStatus.NOT_FOUND, "Unable to find info for track " + str(track_id))
    info = info.json()
    fileformat = info.get('fileformat', '.mp3')  # fileformat added to server API version 3.1
    dir1 = str(track_id // 10000)
    dir2 = str((track_id % 10000) // 1000)
    leaf = str(track_id) + fileformat
    return app.cache_path / dir1 / dir2 / leaf


def ensure_cache_exists(tracks: List[DownloadInfo]):
    if not app:
        abort(HTTPStatus.SERVICE_UNAVAILABLE, APP_NOT_INIT_ERROR)
    for track in tracks:
        if os.path.isfile(track.filepath):
            continue
        fetch = requests.get(f'{app.primary}/mp3/{track.fake_trackid}', timeout=REQUEST_TIMEOUT)
        if not fetch.ok:
            abort(HTTPStatus.NOT_FOUND, "Unable to find audio data for track " + str(track.fake_trackid))
        os.makedirs(os.path.dirname(track.filepath), exist_ok=True)
        with open(track.filepath, 'wb') as handle:
            handle.write(fetch.content)


def play_track_list(tracks: List[DownloadInfo], identifier: str | None, start_at_track_id: int | None):
    assert app
    if start_at_track_id is None:
        play_from_index = 0
    else:
        for index, track in enumerate(tracks):
            if track.fake_trackid == start_at_track_id:
                play_from_index = index
                break
        else:
            abort(HTTPStatus.BAD_REQUEST, "Requested track is not in the specified album")
    ensure_cache_exists(tracks)
    app.current_player.set_queue(tracks, identifier)
    app.current_player.play_from_real_queue_index(play_from_index)


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('-c', '--cache-path', type=Path, metavar='DIR',
                        help="Save local cache files to DIR")
    parser.add_argument('primary',
                        help="Specify the primary server's IP address and port")
    parser.set_defaults(cache_path=Path(__file__).parent.parent.parent / 'cache')
    args = parser.parse_args()
    primary = urllib.parse.urlparse(args.primary)
    if not primary.scheme:
        primary = primary._replace(scheme='http')
    if not primary.netloc:
        parser.error("Unable to parse primary server location")
    if primary.path:
        primary = primary._replace(path='')
    args.primary = urllib.parse.urlunparse(primary)
    return args


def main():
    global app
    args = parse_args()
    app = ReplicaApp(args.cache_path, args.primary)
    app.register_blueprint(routes)
    sock.init_app(app)
    app.run(use_reloader=False, host='0.0.0.0', threaded=True)


if __name__ == '__main__':
    main()
