from argparse import ArgumentParser
from http import HTTPStatus
import json
import os
from pathlib import Path
from typing import List, Optional
import urllib.parse

from flask import abort, Blueprint, Flask, redirect, request
from flask_sock import Sock
import requests

from pijuv2.backend.routeconsts import RouteConstants

from ..backend.downloadinfo import DownloadInfo
from ..backend.deserialize import extract_id
from ..backend.routes import gzippable_jsonify
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
        # TODO: CurrentTrack, CurrentArtwork
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
    ensure_cached_track_ids_exist([trackid])
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
    album = requests.get(f'{app.primary}/albums/{albumid}', timeout=REQUEST_TIMEOUT)
    if not album.ok:
        abort(HTTPStatus.NOT_FOUND, description="Unknown album id")

    track_uris = album.json()['tracks']
    track_ids = [extract_id(uri) for uri in track_uris]
    track_ids = [trackid for trackid in track_ids if trackid]
    play_track_list(track_ids, app.primary + '/albums/' + str(albumid), trackid)


def play_playlist(playlistid: int, trackid: int | None):
    assert app
    playlist = requests.get(f'{app.primary}/playlists/{playlistid}', timeout=REQUEST_TIMEOUT)
    if not playlist.ok:
        abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
    track_uris = playlist.json()['tracks']
    track_ids = [extract_id(uri) for uri in track_uris]
    track_ids = [trackid for trackid in track_ids if trackid]
    play_track_list(track_ids, app.primary + '/playlists/' + str(playlistid), trackid)


def play_track(trackid: int):
    track_ids = [trackid]
    play_track_list(track_ids, None, trackid)  # There is no tracklist URI when we're playing a single track


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


def ensure_cached_track_ids_exist(track_ids: List[int]) -> List[DownloadInfo]:
    tracks = [DownloadInfo(filepath=cache_path(track_id),
                           artist='TODO',
                           title='TODO',
                           artwork=None,
                           url='',
                           fake_trackid=track_id) for track_id in track_ids]
    ensure_cache_exists(tracks)
    return tracks


def play_track_list(track_ids: List[int], identifier: str | None, start_at_track_id: int | None):
    assert app
    if start_at_track_id is None:
        play_from_index = 0
    else:
        try:
            play_from_index = track_ids.index(start_at_track_id)
        except ValueError:
            abort(HTTPStatus.BAD_REQUEST, "Requested track is not in the specified album")
    tracks = ensure_cached_track_ids_exist(track_ids)
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
    app.run(use_reloader=False, host='0.0.0.0', threaded=True)


if __name__ == '__main__':
    main()
