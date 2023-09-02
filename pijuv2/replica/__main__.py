from argparse import ArgumentParser
from collections import namedtuple
from http import HTTPStatus
import os
from pathlib import Path
from typing import List
import urllib.parse

from flask import abort, Flask, request
import requests

from ..backend.__main__ import extract_id, gzippable_jsonify
from ..player.fileplayer import MusicPlayer

app = Flask(__name__)

REQUEST_TIMEOUT = 300  # timeout, in seconds, for requests.get()

# duck-typing: a LocalTrack is like a database.schema.Track - for the bits we need, at least
LocalTrack = namedtuple('LocalTrack', 'Filepath, Id')


# ROUTES ------------------------------------------------------------------------------------------

@app.route("/")
def current_status():
    rtn = {
        'PlayerStatus': app.player.current_status,
        'PlayerVolume': app.player.current_volume,
        'CurrentTracklistUri': app.player.current_tracklist_identifier,
        'CurrentTrackId': app.player.current_track_id,
        'CurrentTrackIndex': None if (app.player.index is None) else (app.player.index + 1),
        'MaximumTrackIndex': app.player.maximum_track_index,
        'ApiVersion': app.api_version_string,
    }
    return gzippable_jsonify(rtn)


@app.route("/cache/<int:trackid>")
def cache(trackid):
    ensure_cached_track_ids_exist([trackid])
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/next", methods=['POST'])
def update_player_next():
    app.player.next()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/pause", methods=['POST'])
def update_player_pause():
    app.player.pause()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/play", methods=['POST'])
def update_player_play():
    data = request.get_json()
    if not data:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')

    albumid = extract_id(data.get('album'))
    playlistid = extract_id(data.get('playlist'))
    queue_pos = extract_id(data.get('queuepos'))
    trackid = extract_id(data.get('track'))

    if sum(x is not None for x in [albumid, playlistid, queue_pos]) > 1:
        abort(HTTPStatus.BAD_REQUEST, "At most one of album, playlist and queuepos may be specified")

    if albumid is not None:
        album = requests.get(f'{app.primary}/albums/{albumid}', timeout=REQUEST_TIMEOUT)
        if not album.ok:
            abort(HTTPStatus.NOT_FOUND, description="Unknown album id")

        track_uris = album.json()['tracks']
        track_ids = [extract_id(uri) for uri in track_uris]
        play_track_list(track_ids, app.primary + '/albums/' + str(albumid), trackid)

    elif playlistid is not None:
        playlist = requests.get(f'{app.primary}/playlists/{playlistid}', timeout=REQUEST_TIMEOUT)
        if not playlist.ok:
            abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
        track_uris = playlist.json()['tracks']
        track_ids = [extract_id(uri) for uri in track_uris]
        play_track_list(track_ids, app.primary + '/playlists/' + str(playlistid), trackid)

    elif queue_pos is not None:
        # We're moving withing the queue: the cached versions should already exist
        if not app.player.play_from_apparent_queue_index(queue_pos, trackid=trackid):
            abort(409, "Track index not found")

    elif trackid:
        track_ids = [trackid]
        play_track_list(track_ids, None, trackid)  # There is no tracklist URI when we're playing a single track

    else:
        abort(HTTPStatus.BAD_REQUEST, description='Album, playlist or track must be specified')

    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/previous", methods=['POST'])
def update_player_prev():
    app.player.prev()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/resume", methods=['POST'])
def update_player_resume():
    app.player.resume()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/stop", methods=['POST'])
def update_player_stop():
    app.player.stop()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/volume", methods=['GET', 'POST'])
def player_volume():
    if request.method == 'GET':
        return {"volume": app.player.current_volume}

    elif request.method == 'POST':
        data = request.get_json()
        if not data:
            abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
        try:
            volume = data.get('volume')
            volume = int(volume)
            app.player.set_volume(volume)
            return ('', HTTPStatus.NO_CONTENT)
        except (AttributeError, KeyError, ValueError):
            abort(HTTPStatus.BAD_REQUEST, description='Volume must be specified and numeric')


# APPLICATION -------------------------------------------------------------------------------------

def cache_path(track_id):
    info = requests.get(f'{app.primary}/tracks/{track_id}', timeout=REQUEST_TIMEOUT)
    if not info.ok:
        abort(HTTPStatus.NOT_FOUND, "Unable to find info for track " + str(track_id))
    info = info.json()
    fileformat = info.get('fileformat', '.mp3')  # fileformat added to server API version 3.1
    dir1 = str(track_id // 10000)
    dir2 = str((track_id % 10000) // 1000)
    leaf = str(track_id) + fileformat
    return str(app.cache_path / dir1 / dir2 / leaf)


def ensure_cache_exists(tracks: List[LocalTrack]):
    for track in tracks:
        if os.path.isfile(track.Filepath):
            continue
        fetch = requests.get(f'{app.primary}/mp3/{track.Id}', timeout=REQUEST_TIMEOUT)
        if not fetch.ok:
            abort(HTTPStatus.NOT_FOUND, "Unable to find audio data for track " + str(track.Id))
        os.makedirs(os.path.dirname(track.Filepath), exist_ok=True)
        with open(track.Filepath, 'wb') as handle:
            handle.write(fetch.content)


def ensure_cached_track_ids_exist(track_ids: List[int]) -> List[LocalTrack]:
    tracks = [LocalTrack(Filepath=cache_path(track_id), Id=track_id) for track_id in track_ids]
    ensure_cache_exists(tracks)
    return tracks


def play_track_list(track_ids: List[int], identifier: str, start_at_track_id: int):
    if start_at_track_id is None:
        play_from_index = 0
    else:
        try:
            play_from_index = track_ids.index(start_at_track_id)
        except ValueError:
            abort(HTTPStatus.BAD_REQUEST, "Requested track is not in the specified album")
    tracks = ensure_cached_track_ids_exist(track_ids)
    app.player.set_queue(tracks, identifier)
    app.player.play_from_real_queue_index(play_from_index)


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
    args = parse_args()
    app.cache_path = args.cache_path
    app.primary = args.primary
    app.player = MusicPlayer()
    app.api_version_string = '4.2'
    app.run(use_reloader=False, host='0.0.0.0', threaded=True)


if __name__ == '__main__':
    main()
