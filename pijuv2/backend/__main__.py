from argparse import ArgumentParser
from collections import defaultdict
import doctest
import gzip
from http import HTTPStatus
import json
import logging
import mimetypes
import os.path
from pathlib import Path
from queue import Queue
from typing import Iterable, List, Tuple

from flask import abort, Flask, make_response, request, Response, url_for
from werkzeug.exceptions import BadRequest, BadRequestKeyError

from ..database.database import Database, DatabaseAccess, NotFoundException
from ..database.schema import Playlist, PlaylistEntry, RadioStation, Track
from ..player.fileplayer import FilePlayer
from ..player.playerinterface import CurrentStatusStrings
from ..player.streamplayer import StreamPlayer
from .config import Config
from .downloadhistory import DownloadHistory
from .downloadinfo import DownloadInfo, DownloadInfoDatabaseSingleton
from .serialize import InformationLevel
from .serialize import json_album, json_genre, json_playlist, json_radio_station, json_track, json_track_or_file
from .workrequests import WorkRequests
from .workthread import WorkerThread


app = Flask(__name__)

mimetypes.init()


# HELPER FUNCTIONS ----------------------------------------------------------------------------


def build_playlist_from_api_data(db: Database) -> Tuple[Playlist, List[str]]:
    data = request.get_json()
    if not data:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    title = data.get('title')
    trackids = extract_ids(data.get('tracks', []))
    files = data.get('files', [])
    if title in (None, ""):
        abort(HTTPStatus.BAD_REQUEST, "Playlist title must be specified")
    if (not trackids) and (not files):
        abort(HTTPStatus.BAD_REQUEST, "Either a list of tracks or a list of files must be specified")
    if (trackids) and (files):
        abort(HTTPStatus.BAD_REQUEST,
              "Only one of a list of tracks and a list of files is permitted")
    if files:
        tracks = []
        missing = []
        for filepath in files:
            fullpath = app.piju_config.music_dir / filepath
            track = db.get_track_by_filepath(str(fullpath))
            if track:
                tracks.append(track)
            else:
                print(f"Could not find a track at {filepath} - looked in {fullpath}")
                missing.append(filepath)
    else:
        missing = []
        if None in trackids:
            abort(HTTPStatus.BAD_REQUEST, "Invalid track reference")
        try:
            tracks = [db.get_track_by_id(trackid) for trackid in trackids]
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
    if not tracks:
        abort(HTTPStatus.BAD_REQUEST, "No tracks found. Will not create an empty playlist.")
    playlist_entries = []
    for index, track in enumerate(tracks):
        playlist_entries.append(PlaylistEntry(PlaylistIndex=index, TrackId=track.Id))
    genres = set(track.Genre for track in tracks if track.Genre is not None)
    genres = list(genres)
    genres = [db.get_genre_by_id(genre) for genre in genres]
    return Playlist(Title=title, Entries=playlist_entries, Genres=genres), missing


def build_radio_station_from_api_data() -> RadioStation:
    data = request.get_json()
    if data is None:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    station_name = data.get('name')
    if not station_name:
        abort(HTTPStatus.BAD_REQUEST, description='Missing station name')
    url = data.get('url')
    if not url:
        abort(HTTPStatus.BAD_REQUEST, description='Missing station URL')
    artwork_url = data.get('artwork')  # optional
    now_playing_url = data.get('now_playing_url')  # optional
    now_playing_jq = data.get('now_playing_jq')  # optional
    now_playing_artwork_url = data.get('now_playing_artwork_url')  # optional
    now_playing_artwork_jq = data.get('now_playing_artwork_jq')  # optional
    return RadioStation(Name=station_name, Url=url, ArtworkUrl=artwork_url,
                        NowPlayingUrl=now_playing_url, NowPlayingJq=now_playing_jq,
                        NowPlayingArtworkUrl=now_playing_artwork_url, NowPlayingArtworkJq=now_playing_artwork_jq)


def extract_id(uri_or_id):
    """
    >>> extract_id("")
    >>> extract_id("/albums/85")
    85
    >>> extract_id("/tracks/123")
    123
    >>> extract_id("/albums/12X")
    >>> extract_id("123")
    123
    >>> extract_id("cat")
    >>> extract_id(432)
    432
    """
    if uri_or_id and isinstance(uri_or_id, str) and '/' in uri_or_id:
        # this is a uri, map it to a string representation of an id, then fall-through
        uri_or_id = uri_or_id.rsplit('/', 1)[1]
    if uri_or_id and isinstance(uri_or_id, str) and uri_or_id.isdigit():
        uri_or_id = int(uri_or_id)
    return uri_or_id if isinstance(uri_or_id, int) else None


def extract_ids(uris_or_ids):
    """
    >>> extract_ids(["/tracks/123", "456", 789])
    [123, 456, 789]
    """
    return [extract_id(uri_or_id) for uri_or_id in uris_or_ids]


def gzippable_jsonify(content):
    content = json.dumps(content, separators=(',', ':'))  # avoid whitespace in response
    if 'gzip' in request.headers.get('Accept-Encoding', '').lower():
        content = gzip.compress(content.encode('utf-8'), 5)
    response = make_response(content)
    response.headers['Content-Length'] = len(content)
    response.headers['Content-Encoding'] = 'gzip'
    return response


def normalize_punctuation(search_string):
    return search_string.replace(chr(0x2018), "'")\
                        .replace(chr(0x2019), "'")\
                        .replace(chr(0x201c), '"')\
                        .replace(chr(0x201d), '"')


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('-a', '--mp3audiodevice', action='store',
                        help='Set audio device for mpg123')
    parser.add_argument('-c', '--config', metavar='FILE', type=Path,
                        help=f"Load configuration from FILE. Default is {str(Config.default_filepath())}")
    parser.add_argument('-d', '--database', metavar='FILE', type=Path,
                        help="Set database path to FILE. Default is %(default)s")
    parser.add_argument('-t', '--doctest', action='store_true',
                        help="Run self-test and exit")
    parser.set_defaults(doctest=False,
                        config=None,
                        database='file.db')
    args = parser.parse_args()
    if args.config and not args.config.is_file():
        parser.error(f"Specified configuration file ({str(args.config)}) could not be found")
    if (args.config is None) and (Config.default_filepath().is_file()):
        args.config = Config.default_filepath()
    if not args.database.is_file():
        parser.error("Specified database file does not exist. Use `run.sh` (or alembic) to initialise the database")
    return args


def parse_bool(bool_str: str):
    """
    >>> parse_bool('yes')
    True
    >>> parse_bool('y')
    True
    >>> parse_bool('Y')
    True
    >>> parse_bool('True')
    True
    >>> parse_bool('False')
    False
    >>> parse_bool('XYZ')
    False
    """
    if bool_str.lower() in ('y', 'yes', 'true'):
        return True
    return False


def response_for_import_playlist(playlist: Playlist, missing_tracks: List[str]):
    response = {
        'playlistid': playlist.Id,
        'nrtracks': len(playlist.Entries),
        'missing': missing_tracks,
    }
    return gzippable_jsonify(response)


# PLAYBACK HELPER FUNCTIONS -----------------------------------------------------------------------


def play_downloaded_files(url, download_info: Iterable[DownloadInfo]):
    """
    A callback after an audio URL has been downloaded
    """
    select_player(app.file_player)
    app.current_player.clear_queue()
    queue_downloaded_files(url, download_info)


def play_track_list(tracks: List[Track], identifier: str, start_at_track_id: int):
    if start_at_track_id is None:
        play_from_index = 0
    else:
        track_ids = [track.Id for track in tracks]
        try:
            play_from_index = track_ids.index(start_at_track_id)
        except ValueError:
            abort(HTTPStatus.BAD_REQUEST, "Requested track is not in the specified album")
    select_player(app.file_player)
    app.current_player.set_queue(tracks, identifier)
    app.current_player.play_from_real_queue_index(play_from_index)


def queue_downloaded_files(url, download_info: Iterable[DownloadInfo]):
    select_player(app.file_player)
    app.download_history.set_info(url, download_info)
    for one_download in download_info:
        app.current_player.add_to_queue(str(one_download.filepath),
                                        one_download.fake_trackid,
                                        one_download.artist, one_download.title,
                                        one_download.artwork)


def select_player(desired_player):
    if (app.current_player != desired_player) and (app.current_player is not None):
        app.current_player.stop()
    app.current_player = desired_player


def update_player_play_album(db, albumid, trackid):
    try:
        album = db.get_album_by_id(albumid)
    except NotFoundException:
        abort(HTTPStatus.NOT_FOUND, description="Unknown album id")

    def track_sort_order(track):
        return (track.VolumeNumber if track.VolumeNumber else 0,
                track.TrackNumber if track.TrackNumber else 0)
    tracks = list(sorted(album.Tracks, key=track_sort_order))
    play_track_list(tracks, url_for('get_album', albumid=albumid), trackid)


def update_player_play_from_queue(queue_pos, trackid):
    # update_player_play has already ensured we're set up for file playback
    if not app.current_player.play_from_apparent_queue_index(queue_pos, trackid=trackid):
        abort(409, "Track index not found")


def update_player_play_from_radio(db: Database, stationid: int):
    stations = db.get_all_radio_stations()
    index = next((i for i, station in enumerate(stations) if station.Id == stationid), -1)
    if index == -1:
        abort(HTTPStatus.NOT_FOUND, "Requested station id not found")
    station = stations[index]
    select_player(app.stream_player)
    app.current_player.play(station.Name, station.Url, station.ArtworkUrl,
                            index, len(stations),
                            station.NowPlayingUrl, station.NowPlayingJq,
                            station.NowPlayingArtworkUrl, station.NowPlayingArtworkJq)


def update_player_play_from_youtube(url):
    app.download_history.add(url)
    app.work_queue.put((WorkRequests.FETCH_FROM_YOUTUBE, url, app.piju_config.download_dir, play_downloaded_files))


def update_player_play_playlist(db: Database, playlistid, trackid):
    try:
        playlist = db.get_playlist_by_id(playlistid)
    except NotFoundException:
        abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
    play_track_list([entry.Track for entry in playlist.Entries],
                    url_for('one_playlist', playlistid=playlistid),
                    trackid)


def update_player_play_track(db: Database, trackid):
    # update_player_play has already ensured we're set up for file playback
    try:
        track = db.get_track_by_id(trackid)
    except NotFoundException:
        abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
    app.current_player.clear_queue()
    add_track_to_queue(track)


def update_player_streaming_prevnext(delta):
    current_url = app.current_player.currently_playing_url
    with DatabaseAccess() as db:
        stations = db.get_all_radio_stations()
        current_index = next((i for i, station in enumerate(stations) if station.Url == current_url), -1)
        if current_index > -1:
            new_index = current_index + delta
            if 0 <= new_index < len(stations):
                new_station = stations[new_index]
                app.current_player.play(new_station.Name, new_station.Url, new_station.ArtworkUrl,
                                        new_index, len(stations),
                                        new_station.NowPlayingUrl, new_station.NowPlayingJq,
                                        new_station.NowPlayingArtworkUrl, new_station.NowPlayingArtworkJq)


# RESPONSE HEADERS --------------------------------------------------------------------------------

@app.after_request
def add_security_headers(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


# ROUTES ------------------------------------------------------------------------------------------

@app.route("/")
def current_status():
    with DatabaseAccess() as db:
        c_p = app.current_player
        rtn = {
            'WorkerStatus': app.worker.current_status,
            'PlayerStatus': c_p.current_status,
            'PlayerVolume': c_p.current_volume,
            'NumberAlbums': db.get_nr_albums(),
            'NumberTracks': db.get_nr_tracks(),
            'CurrentTrackIndex': None if (c_p.current_track_index is None) else (c_p.current_track_index + 1),
            'MaximumTrackIndex': c_p.number_of_tracks,
            'ApiVersion': app.api_version_string,
        }
        if c_p == app.file_player:
            rtn['CurrentTracklistUri'] = c_p.current_tracklist_identifier
            if c_p.current_track:
                rtn['CurrentTrack'] = json_track_or_file(db, c_p.current_track)
                rtn['CurrentArtwork'] = rtn['CurrentTrack']['artwork']
            else:
                rtn['CurrentTrack'] = {}
                rtn['CurrentArtwork'] = None
        elif c_p == app.stream_player:
            rtn['CurrentStream'] = c_p.currently_playing_name
            rtn['CurrentArtwork'] = c_p.currently_playing_artwork
            if c_p.current_status == CurrentStatusStrings.PLAYING and c_p.now_playing_artist and c_p.now_playing_track:
                rtn['CurrentTrack'] = {
                    'artist': c_p.now_playing_artist,
                    'title': c_p.now_playing_track
                }

    return gzippable_jsonify(rtn)


@app.route("/albums/")
def get_all_albums():
    with DatabaseAccess() as db:
        rtn = []
        for album in db.get_all_albums():
            rtn.append(json_album(album, include_tracks=InformationLevel.NoInfo))
        return gzippable_jsonify(rtn)


@app.route("/albums/<albumid>")
def get_album(albumid):
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown album id")
        return gzippable_jsonify(json_album(album, include_tracks=track_info))


@app.route("/artists/<artist>")
def get_artist(artist):
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
    exact = parse_bool(request.args.get('exact', 'True'))
    with DatabaseAccess() as db:
        albums = db.get_artist(artist, substring=not exact)
        if not albums:
            abort(HTTPStatus.NOT_FOUND, description="No matching artist found")
        result = defaultdict(list)
        for album in albums:
            result[album.Artist].append(json_album(album, include_tracks=track_info))
        return gzippable_jsonify(result)


@app.route("/artwork/<trackid>")
def get_artwork(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")

        if track.ArtworkPath:
            path = Path(track.ArtworkPath)
            mime = mimetypes.types_map[path.suffix]
            with open(track.ArtworkPath, 'rb') as handle:
                data = handle.read()

            return Response(data, headers={'Cache-Control': 'max-age=300'}, mimetype=mime)

        elif track.ArtworkBlob:
            if track.ArtworkBlob[:3] == b'\xff\xd8\xff':
                mime = mimetypes.types_map['.jpg']
            elif track.ArtworkBlob[:8] == b'\x89\x50\x4e\x47\x0d\x0a\x1a\x0a':
                mime = mimetypes.types_map['.png']
            else:
                abort(500, description="Unknown mime type")

            return Response(track.ArtworkBlob, headers={'Cache-Control': 'max-age=300'}, mimetype=mime)

        else:
            return abort(HTTPStatus.NOT_FOUND, description="Track has no artwork")


@app.route("/artworkinfo/<trackid>")
def get_artwork_info(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")

        has_artwork = (track.ArtworkPath or track.ArtworkBlob)
        rtn = {
            "width": track.ArtworkWidth,
            "height": track.ArtworkHeight,
            "image": url_for('get_artwork', trackid=trackid) if has_artwork else None,
        }
        return gzippable_jsonify(rtn)


@app.route("/downloadhistory")
def get_download_history():
    rtn = []
    for url in app.download_history.entries:
        files = app.download_history.get_info(url)
        if files:
            # reverse the playlist so most recent is first in the list
            for download_info in reversed(files):
                rtn.append({
                    'url': download_info.url,  # not necessarily the same as url - eg playlist
                    'artist': download_info.artist,
                    'title': download_info.title,
                    'artwork': download_info.artwork
                })
        else:
            rtn.append({'url': url})
    return gzippable_jsonify(rtn)


@app.route("/genres/")
def get_all_genres():
    with DatabaseAccess() as db:
        rtn = []
        for genre in db.get_all_genres():
            rtn.append(json_genre(genre,
                                  include_albums=InformationLevel.NoInfo,
                                  include_playlists=InformationLevel.NoInfo))
        return gzippable_jsonify(rtn)


@app.route("/genres/<genreid>")
def get_genre(genreid):
    album_info = InformationLevel.from_string(request.args.get('albums', ''))
    playlist_info = InformationLevel.from_string(request.args.get('playlists', ''))
    with DatabaseAccess() as db:
        try:
            genre = db.get_genre_by_id(genreid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown genre id")
        return gzippable_jsonify(json_genre(genre, include_albums=album_info, include_playlists=playlist_info))


@app.route("/mp3/<trackid>")
def get_mp3(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")

        with open(track.Filepath, 'rb') as handle:
            content = handle.read()
        response = make_response(content)
        response.headers['Content-Type'] = 'audio/mpeg'
        response.headers['Content-Length'] = len(content)
        return response


@app.route("/player/next", methods=['POST'])
def update_player_next():
    if app.current_player == app.file_player:
        app.current_player.next()
    else:
        update_player_streaming_prevnext(1)
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/pause", methods=['POST'])
def update_player_pause():
    app.current_player.pause()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/play", methods=['POST'])
def update_player_play():
    data = request.get_json()
    if not data:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    with DatabaseAccess() as db:
        albumid = extract_id(data.get('album'))
        playlistid = extract_id(data.get('playlist'))
        queue_pos = extract_id(data.get('queuepos'))
        trackid = extract_id(data.get('track'))
        radioid = extract_id(data.get('radio'))
        youtubeurl = data.get('url')

        # Valid requests:
        #   album with or without track
        #   playlist with or without track
        #   queuepos with or without track
        #   track on its own
        #   youtubeurl (with nothing else)
        #   radio (with nothing else)

        if not any([albumid, playlistid, queue_pos, trackid, radioid, youtubeurl]):
            abort(HTTPStatus.BAD_REQUEST, description='Something to play must be specified')

        if sum(x is not None for x in [albumid, playlistid, queue_pos]) > 1:
            abort(HTTPStatus.BAD_REQUEST, "At most one of album, playlist and queuepos may be specified")

        if radioid and any([albumid, playlistid, queue_pos, trackid, youtubeurl]):
            abort(HTTPStatus.BAD_REQUEST, "A radio station may not be specified with any other track selection")

        if youtubeurl and any([albumid, playlistid, queue_pos, trackid, radioid]):
            abort(HTTPStatus.BAD_REQUEST, "A URL may not be specified with any other track selection")

        if youtubeurl:
            update_player_play_from_youtube(youtubeurl)

        elif radioid:
            update_player_play_from_radio(db, radioid)

        else:
            # File-based playback required
            select_player(app.file_player)

            if albumid is not None:
                update_player_play_album(db, albumid, trackid)

            elif playlistid is not None:
                update_player_play_playlist(db, playlistid, trackid)

            elif queue_pos is not None:
                update_player_play_from_queue(queue_pos, trackid)

            elif trackid:
                update_player_play_track(db, trackid)

            else:
                assert False, "Internal error: Unhandled code path"

    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/previous", methods=['POST'])
def update_player_prev():
    if app.current_player == app.file_player:
        app.current_player.prev()
    else:
        update_player_streaming_prevnext(-1)
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/resume", methods=['POST'])
def update_player_resume():
    app.current_player.resume()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/stop", methods=['POST'])
def update_player_stop():
    app.current_player.stop()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/volume", methods=['GET', 'POST'])
def player_volume():
    if request.method == 'GET':
        return {"volume": app.current_player.current_volume}

    elif request.method == 'POST':
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

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@app.route("/playlists/", methods=['GET', 'POST'])
def playlists():
    if request.method == 'GET':
        genre_info = InformationLevel.from_string(request.args.get('genres', ''), InformationLevel.NoInfo)
        tracks_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.NoInfo)
        with DatabaseAccess() as db:
            rtn = []
            for playlist in db.get_all_playlists():
                rtn.append(json_playlist(playlist, include_genres=genre_info, include_tracks=tracks_info))
            return gzippable_jsonify(rtn)

    elif request.method == 'POST':
        with DatabaseAccess() as db:
            playlist, missing = build_playlist_from_api_data(db)
            db.create_playlist(playlist)
            return response_for_import_playlist(playlist, missing)

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@app.route("/playlists/<playlistid>", methods=['DELETE', 'GET', 'PUT'])
def one_playlist(playlistid):
    if request.method == 'GET':
        genre_info = InformationLevel.from_string(request.args.get('genres', ''), InformationLevel.NoInfo)
        track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
        with DatabaseAccess() as db:
            try:
                playlist = db.get_playlist_by_id(playlistid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
            return gzippable_jsonify(json_playlist(playlist, include_genres=genre_info, include_tracks=track_info))

    elif request.method == 'PUT':
        with DatabaseAccess() as db:
            playlist, missing = build_playlist_from_api_data(db)
            playlist = db.update_playlist(playlistid, playlist)
            return response_for_import_playlist(playlist, missing)

    elif request.method == 'DELETE':
        with DatabaseAccess() as db:
            try:
                db.delete_playlist(playlistid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
            return ('', HTTPStatus.NO_CONTENT)

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@app.route("/queue/", methods=['GET', 'DELETE', 'OPTIONS', 'PUT'])
def queue():
    if app.current_player != app.file_player:
        abort(HTTPStatus.CONFLICT, "Queue operations not permitted when playing streaming content")
    if request.method == 'DELETE':
        data = request.get_json()
        if not data:
            raise BadRequest()
        try:
            index = int(data['index'])
            trackid = int(data['track'])
        except KeyError as exc:
            raise BadRequestKeyError() from exc
        except ValueError as exc:
            raise BadRequest() from exc
        if not app.current_player.remove_from_queue(index, trackid):
            # index or trackid mismatch
            raise BadRequest('Track id did not match at given index')
        return ('', HTTPStatus.NO_CONTENT)

    elif request.method == 'GET':
        with DatabaseAccess() as db:
            queue_data = [json_track_or_file(db, queued_track) for queued_track in app.current_player.visible_queue]
        return gzippable_jsonify(queue_data)

    elif request.method == 'OPTIONS':
        # the request to add to queue looks like a cross-domain request to Chrome,
        # so it sends OPTIONS before the PUT. Hence we need to support this.
        response = make_response('', HTTPStatus.NO_CONTENT)
        response.headers['Access-Control-Allow-Headers'] = '*'  # Maybe tighten this up?
        response.headers['Access-Control-Allow-Methods'] = ', '.join(request.url_rule.methods)
        return response

    elif request.method == 'PUT':
        data = request.get_json()
        if not data:
            abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
        # there are three different possibilities here:
        #   track: trackid  # add the given track to queue
        #   url: url        # add the audio from the given URL to queue
        #   queue: [trackid_or_url]  # reorder the queue
        if trackid := extract_id(data.get('track', '')):
            with DatabaseAccess() as db:
                try:
                    add_track_to_queue(db.get_track_by_id(trackid))
                except NotFoundException:
                    abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
        elif youtubeurl := data.get('url'):
            app.download_history.add(youtubeurl)
            app.work_queue.put((WorkRequests.FETCH_FROM_YOUTUBE, youtubeurl, app.piju_config.download_dir,
                                queue_downloaded_files))
        elif new_queue_order := data.get('queue'):
            new_queue = []
            with DatabaseAccess() as db:
                try:
                    for trackid in new_queue_order:
                        trackid = int(trackid)
                        if trackid >= 0:
                            new_queue.append(db.get_track_by_id(trackid))
                        else:
                            new_queue.append(DownloadInfoDatabaseSingleton().get_download_info(trackid))
                except NotFoundException:
                    abort(HTTPStatus.NOT_FOUND, "Unknown track id")
                except ValueError:
                    abort(HTTPStatus.BAD_REQUEST, "Unrecognised track id")
                app.current_player.set_queue(new_queue, "/queue/")
        else:
            abort(HTTPStatus.BAD_REQUEST, "No track id, url or new queue order specified")
        return ('', HTTPStatus.NO_CONTENT)

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


def add_track_to_queue(track: Track):
    """
    Pre-requisite: the caller is responsible for ensuring that current_player
    is a queueing-capable player (ie the file_player)
    """
    has_artwork = (track.ArtworkPath or track.ArtworkBlob)
    artwork_uri = url_for('get_artwork', trackid=track.Id) if has_artwork else None
    app.current_player.add_to_queue(track.Filepath, track.Id, track.Artist, track.Title, artwork_uri)


@app.route("/radio/", methods=['GET', 'OPTIONS', 'POST', 'PUT'])
def radio_stations():
    if request.method == 'GET':
        with DatabaseAccess() as db:
            rtn = []
            for station in db.get_all_radio_stations():
                rtn.append(json_radio_station(station))
            return gzippable_jsonify(rtn)

    elif request.method == 'OPTIONS':
        response = make_response('', HTTPStatus.NO_CONTENT)
        response.headers['Access-Control-Allow-Headers'] = ', '.join(['Content-Type',
                                                                      'Access-Control-Allow-Headers',
                                                                      'Access-Control-Allow-Methods',
                                                                      'Access-Control-Allow-Origin'])
        response.headers['Access-Control-Allow-Methods'] = ', '.join(request.url_rule.methods)

    elif request.method == 'POST':
        station = build_radio_station_from_api_data()
        with DatabaseAccess() as db:
            db.add_radio_station(station)
            response = {
                'id': station.Id
            }
            return gzippable_jsonify(response)

    elif request.method == 'PUT':
        # reorder stations
        desired_station_order = request.get_json()
        if not isinstance(desired_station_order, list):
            abort(HTTPStatus.BAD_REQUEST, "List of station identifiers expected")
        desired_station_order = [extract_id(station) for station in desired_station_order]
        if None in desired_station_order:
            abort(HTTPStatus.BAD_REQUEST, "Unrecognised station id in list")
        with DatabaseAccess() as db:
            stations = db.get_all_radio_stations()
            if len(desired_station_order) != len(stations) or len(set(desired_station_order)) != len(stations):
                msg = "Submitted list does not specify the order for all stations, or contains duplicates"
                abort(HTTPStatus.BAD_REQUEST, msg)
            for station in stations:
                station.SortOrder = desired_station_order.index(station.Id)
        return ('', HTTPStatus.NO_CONTENT)

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@app.route("/radio/<stationid>", methods=['DELETE', 'GET', 'PUT'])
def one_radio_station(stationid):
    if request.method == 'GET':
        infolevel = InformationLevel.from_string(request.args.get('urls', ''), InformationLevel.Links)
        include_urls = (infolevel in (InformationLevel.AllInfo, InformationLevel.DebugInfo))
        with DatabaseAccess() as db:
            try:
                station = db.get_radio_station_by_id(stationid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown radio station id")
            return gzippable_jsonify(json_radio_station(station, include_urls=include_urls))

    elif request.method == 'PUT':
        station = build_radio_station_from_api_data()
        with DatabaseAccess() as db:
            existing_station = db.update_radio_station(stationid, station)
            return gzippable_jsonify(json_radio_station(existing_station))

    elif request.method == 'DELETE':
        with DatabaseAccess() as db:
            try:
                db.delete_radio_station(stationid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description='Unknown radio station id')
            return ('', HTTPStatus.NO_CONTENT)
    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@app.route("/scanner/scan", methods=['POST'])
def start_scan():
    data = request.get_json()
    if data is None:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    subdir = data.get('dir')
    scandir = app.piju_config.music_dir if (subdir is None) else os.path.join(app.piju_config.music_dir, subdir)
    if not os.path.isdir(scandir):
        abort(HTTPStatus.BAD_REQUEST, f"Directory {subdir} does not exist")
    app.work_queue.put((WorkRequests.SCAN_DIRECTORY, scandir))
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/scanner/tidy", methods=['POST'])
def start_tidy():
    app.work_queue.put((WorkRequests.DELETE_MISSING_TRACKS, ))
    app.work_queue.put((WorkRequests.DELETE_ALBUMS_WITHOUT_TRACKS, ))
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/search/<search_string>")
def search(search_string):
    search_words = normalize_punctuation(search_string).strip().split()
    do_search_albums = parse_bool(request.args.get('albums', 'True'))
    do_search_artists = parse_bool(request.args.get('artists', 'True'))
    do_search_tracks = parse_bool(request.args.get('tracks', 'True'))
    with DatabaseAccess() as db:
        rtn = {}
        if do_search_albums:
            albums = db.search_for_albums(search_words)
            rtn['albums'] = [json_album(album, include_tracks=InformationLevel.NoInfo) for album in albums]
        if do_search_artists:
            artist_albums = db.search_for_artist(search_words)
            artists = set(album.Artist for album in artist_albums if album.Artist)
            rtn['artists'] = [{"name": artist, "link": url_for('get_artist', artist=artist)} for artist in artists]
        if do_search_tracks:
            tracks = db.search_for_tracks(search_words)
            rtn['tracks'] = [json_track(track) for track in tracks]
    return gzippable_jsonify(rtn)


@app.route("/tracks/")
def get_all_tracks():
    limit = request.args.get('limit', '')
    if limit and limit.isdigit():
        limit = int(limit)
    else:
        limit = None
    with DatabaseAccess() as db:
        rtn = []
        for track in db.get_all_tracks(limit):
            rtn.append(json_track(track))
        return gzippable_jsonify(rtn)


@app.route("/tracks/<trackid>")
def get_track(trackid):
    infolevel = InformationLevel.from_string(request.args.get('infolevel', ''), InformationLevel.AllInfo)
    include_debuginfo = (infolevel == InformationLevel.DebugInfo)
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
        return gzippable_jsonify(json_track(track, include_debuginfo=include_debuginfo))


# MAIN --------------------------------------------------------------------------------------------

def main():
    args = parse_args()

    if args.doctest:
        doctest.testmod()
    else:
        logging.basicConfig(level=logging.DEBUG)
        Database.DEFAULT_FILENAME = str(args.database)
        config = Config(args.config)
        app.piju_config = config
        app.work_queue = Queue()
        app.worker = WorkerThread(app.work_queue)
        app.worker.start()
        app.file_player = FilePlayer(mp3audiodevice=args.mp3audiodevice)
        app.stream_player = StreamPlayer(audio_device=args.mp3audiodevice)
        app.current_player = app.file_player
        app.api_version_string = '6.0'
        app.download_history = DownloadHistory()
        # macOS: Need to disable AirPlay Receiver for listening on 0.0.0.0 to work
        # see https://developer.apple.com/forums/thread/682332
        app.run(use_reloader=False, host='0.0.0.0', threaded=True)


if __name__ == '__main__':
    main()
