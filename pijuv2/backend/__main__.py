from argparse import ArgumentParser
from collections import defaultdict
import gzip
from http import HTTPStatus
import json
import logging
import mimetypes
import os.path
from pathlib import Path
from queue import Queue
from typing import List, Tuple

from flask import abort, Flask, make_response, request, Response, url_for
from werkzeug.exceptions import BadRequest, BadRequestKeyError

from ..database.database import Database, DatabaseAccess, NotFoundException
from ..database.schema import Album, Genre, Playlist, PlaylistEntry, Track
from ..player.player import MusicPlayer
from .config import Config
from .downloadhistory import DownloadHistory
from .workqueue import WorkRequests
from .workthread import WorkerThread


app = Flask(__name__)

mimetypes.init()


class InformationLevel:
    NoInfo = 0
    Links = 1
    AllInfo = 2
    DebugInfo = 3  # All Info plus information that's not normally exposed via the API (eg file paths)

    @staticmethod
    def from_string(info: str, default: 'InformationLevel' = Links):
        info = info.lower()
        if info == 'none':
            return InformationLevel.NoInfo
        elif info == 'links':
            return InformationLevel.Links
        elif info == 'all':
            return InformationLevel.AllInfo
        elif info == 'debug':
            return InformationLevel.DebugInfo
        else:
            return default


def build_playlist_from_api_data(db: Database, request) -> Tuple[Playlist, List[str]]:
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
        abort(HTTPStatus.BAD_REQUEST, "Only one of a list of tracks and a list of files is permitted")
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


def json_album(album: Album, include_tracks: InformationLevel):
    tracks = list(album.Tracks)
    tracks = sorted(tracks, key=lambda track: (track.VolumeNumber or 0, track.TrackNumber or 0))
    for track in tracks:
        if track.ArtworkPath or track.ArtworkBlob:
            artwork_uri = url_for('get_artwork', trackid=track.Id)
            artwork_width = track.ArtworkWidth
            artwork_height = track.ArtworkHeight
            break
    else:
        artwork_uri = artwork_width = artwork_height = None

    rtn = {
        'link': url_for('get_album', albumid=album.Id),
        'artist': album.Artist,
        'title': album.Title,
        'releasedate': album.ReleaseYear,
        'iscompilation': album.IsCompilation,
        'numberdisks': album.VolumeCount,
        'artwork': {
            'link': artwork_uri,
            'width': artwork_width,
            'height': artwork_height
        },
        'genres': [url_for('get_genre', genreid=genre.Id) for genre in album.Genres],
    }
    if include_tracks == InformationLevel.Links:
        rtn['tracks'] = [url_for('get_track', trackid=track.Id) for track in tracks]
    elif include_tracks in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        include_debuginfo = (include_tracks == InformationLevel.DebugInfo)
        rtn['tracks'] = [json_track(track, include_debuginfo=include_debuginfo) for track in tracks]
    return rtn


def json_genre(genre: Genre, include_albums: InformationLevel, include_playlists: InformationLevel):
    rtn = {
        'link': url_for('get_genre', genreid=genre.Id),
        'name': genre.Name,
    }
    if include_albums == InformationLevel.Links:
        rtn['albums'] = [url_for('get_album', albumid=album.Id) for album in genre.Albums]
    elif include_albums in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        rtn['albums'] = [json_album(album, include_tracks=include_albums) for album in genre.Albums]
    if include_playlists == InformationLevel.Links:
        rtn['playlists'] = [url_for('one_playlist', playlistid=playlist.Id) for playlist in genre.Playlists]
    elif include_playlists in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        rtn['playlists'] = [json_playlist(playlist,
                                          include_genres=InformationLevel.NoInfo,
                                          include_tracks=include_playlists)
                            for playlist in genre.Playlists]
    return rtn


def json_playlist(playlist: Playlist, include_genres: InformationLevel, include_tracks: InformationLevel):
    entries = list(playlist.Entries)
    rtn = {
        'link': url_for('one_playlist', playlistid=playlist.Id),
        'title': playlist.Title,
    }
    if include_genres == InformationLevel.Links:
        rtn['genres'] = [url_for('get_genre', genreid=genre.Id) for genre in playlist.Genres]
    elif include_genres in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        rtn['genres'] = [json_genre(genre,
                                    include_albums=InformationLevel.NoInfo,
                                    include_playlists=InformationLevel.NoInfo) for genre in playlist.Genres]
    if include_tracks == InformationLevel.Links:
        rtn['tracks'] = [url_for('get_track', trackid=entry.TrackId) for entry in entries]
    elif include_tracks in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        include_debuginfo = (include_tracks == InformationLevel.DebugInfo)
        rtn['tracks'] = [json_track(entry.Track, include_debuginfo=include_debuginfo) for entry in entries]
    return rtn


def json_track(track: Track, include_debuginfo: bool = False):
    if not track:
        return {}
    has_artwork = track.ArtworkPath or track.ArtworkBlob
    rtn = {
        'link': url_for('get_track', trackid=track.Id),
        'artist': track.Artist,
        'title': track.Title,
        'genre': track.Genre,
        'disknumber': track.VolumeNumber,
        'tracknumber': track.TrackNumber,
        'trackcount': track.TrackCount,
        'fileformat': os.path.splitext(track.Filepath)[1],
        'album': url_for('get_album', albumid=track.Album) if track.Album else '',
        'artwork': url_for('get_artwork', trackid=track.Id) if has_artwork else None,
        'artworkinfo': url_for('get_artwork_info', trackid=track.Id) if has_artwork else None,
    }
    if include_debuginfo:
        rtn['filepath'] = track.Filepath
    return rtn


def json_track_or_file(db, queued_track, include_debuginfo: bool = False):
    if queued_track.trackid is not None:
        track = db.get_track_by_id(queued_track.trackid)
        return json_track(track, include_debuginfo)
    else:
        rtn = {
            'link': None,
            'artist': queued_track.artist,
            'title': queued_track.title,
            'genre': None,
            'disknumber': None,
            'tracknumber': None,
            'trackcount': None,
            'fileformat': os.path.splitext(queued_track.filepath)[1],
            'album': None,
            'artwork': queued_track.artwork,
            'artworkinfo': None
        }
        if include_debuginfo:
            rtn['filepath'] = queued_track.filepath
        return rtn


def normalize_punctuation(search_string):
    return search_string.replace(chr(0x2018), "'")\
                        .replace(chr(0x2019), "'")\
                        .replace(chr(0x201c), '"')\
                        .replace(chr(0x201d), '"')


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('-a', '--mp3audiodevice', action='store',
                        help='Set audio device for mpg123')
    parser.add_argument('-t', '--doctest', action='store_true',
                        help="Run self-test and exit")
    parser.add_argument('-c', '--config', metavar='FILE', type=Path,
                        help=f"Load configuration from FILE. Default is {str(Config.default_filepath())}")
    parser.set_defaults(doctest=False,
                        config=None)
    args = parser.parse_args()
    if args.config and not args.config.is_file():
        parser.error(f"Specified configuration file ({str(args.config)}) could not be found")
    if (args.config is None) and (Config.default_filepath().is_file()):
        args.config = Config.default_filepath()
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


def play_track_list(tracks: List[Track], identifier: str, start_at_track_id: int):
    if start_at_track_id is None:
        play_from_index = 0
    else:
        track_ids = [track.Id for track in tracks]
        try:
            play_from_index = track_ids.index(start_at_track_id)
        except ValueError:
            abort(HTTPStatus.BAD_REQUEST, "Requested track is not in the specified album")
    app.player.set_queue(tracks, identifier)
    app.player.play_from_real_queue_index(play_from_index)


def response_for_import_playlist(playlist: Playlist, missing_tracks: List[str]):
    response = {
        'playlistid': playlist.Id,
        'nrtracks': len(playlist.Entries),
        'missing': missing_tracks,
    }
    return gzippable_jsonify(response)


# RESPONSE HEADERS --------------------------------------------------------------------------------

@app.after_request
def add_security_headers(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


# ROUTES ------------------------------------------------------------------------------------------

@app.route("/")
def current_status():
    with DatabaseAccess() as db:
        rtn = {
            'WorkerStatus': app.worker.current_status,
            'PlayerStatus': app.player.current_status,
            'PlayerVolume': app.player.current_volume,
            'CurrentTracklistUri': app.player.current_tracklist_identifier,
            'CurrentTrack': json_track_or_file(db, app.player.current_track) if app.player.current_track else {},
            'CurrentTrackIndex': None if (app.player.index is None) else (app.player.index + 1),
            'MaximumTrackIndex': app.player.maximum_track_index,
            'NumberAlbums': db.get_nr_albums(),
            'NumberTracks': db.get_nr_tracks(),
            'ApiVersion': app.api_version_string,
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
            abort(HTTPStatus.NOT_FOUND, description="Track has no artwork")


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
    with DatabaseAccess() as db:
        albumid = extract_id(data.get('album'))
        playlistid = extract_id(data.get('playlist'))
        queue_pos = extract_id(data.get('queuepos'))
        trackid = extract_id(data.get('track'))
        youtubeurl = data.get('url')

        if sum(x is not None for x in [albumid, playlistid, queue_pos]) > 1:
            abort(HTTPStatus.BAD_REQUEST, "At most one of album, playlist and queuepos may be specified")

        if youtubeurl and any([albumid, playlistid, queue_pos, trackid]):
            abort(HTTPStatus.BAD_REQUEST, "A URL may not be specified with any other track selection")

        if youtubeurl:
            update_player_play_from_youtube(youtubeurl)

        elif albumid is not None:
            update_player_play_album(db, albumid, trackid)

        elif playlistid is not None:
            update_player_play_playlist(db, playlistid, trackid)

        elif queue_pos is not None:
            update_player_play_from_queue(queue_pos, trackid)

        elif trackid:
            update_player_play_track(db, trackid)

        else:
            abort(HTTPStatus.BAD_REQUEST, description='Album, playlist or track must be specified')
    return ('', HTTPStatus.NO_CONTENT)


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
    if not app.player.play_from_apparent_queue_index(queue_pos, trackid=trackid):
        abort(409, "Track index not found")


def update_player_play_from_youtube(url):
    app.download_history.add(url)
    app.work_queue.put((WorkRequests.FetchFromYouTube, url, app.piju_config.download_dir, play_downloaded_files))


def play_downloaded_files(url, download_info):
    """
    A callback after an audio URL has been downloaded
    """
    app.player.clear_queue()
    queue_downloaded_files(url, download_info)


def queue_downloaded_files(url, download_info):
    app.download_history.set_info(url, download_info)
    for one_download in download_info:
        app.player.add_to_queue(str(one_download.filepath), None, one_download.artist, one_download.title,
                                one_download.artwork)


def update_player_play_playlist(db, playlistid, trackid):
    try:
        playlist = db.get_playlist_by_id(playlistid)
    except NotFoundException:
        abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
    play_track_list([entry.Track for entry in playlist.Entries],
                    url_for('one_playlist', playlistid=playlistid),
                    trackid)


def update_player_play_track(db, trackid):
    try:
        track = db.get_track_by_id(trackid)
    except NotFoundException:
        abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
    app.player.clear_queue()
    add_track_to_queue(track)


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
            playlist, missing = build_playlist_from_api_data(db, request)
            db.create_playlist(playlist)
            return response_for_import_playlist(playlist, missing)


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
            playlist, missing = build_playlist_from_api_data(db, request)
            playlist = db.update_playlist(playlistid, playlist)
            return response_for_import_playlist(playlist, missing)
    elif request.method == 'DELETE':
        with DatabaseAccess() as db:
            try:
                db.delete_playlist(playlistid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
            return ('', HTTPStatus.NO_CONTENT)


@app.route("/queue/", methods=['GET', 'DELETE', 'OPTIONS', 'PUT'])
def queue():
    if request.method == 'DELETE':
        data = request.get_json()
        if not data:
            raise BadRequest()
        try:
            index = int(data['index'])
            trackid = int(data['track'])
        except KeyError:
            raise BadRequestKeyError()
        except ValueError:
            raise BadRequest()
        if not app.player.remove_from_queue(index, trackid):
            # index or trackid mismatch
            raise BadRequest('Track id did not match at given index')
        return ('', HTTPStatus.NO_CONTENT)

    elif request.method == 'GET':
        with DatabaseAccess() as db:
            queue = [json_track_or_file(db, queued_track) for queued_track in app.player.visible_queue]
        return gzippable_jsonify(queue)

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
        trackid = extract_id(data.get('track', ''))
        youtubeurl = data.get('url')
        if youtubeurl:
            app.download_history.add(youtubeurl)
            app.work_queue.put((WorkRequests.FetchFromYouTube, youtubeurl, app.piju_config.download_dir,
                                queue_downloaded_files))
        else:
            with DatabaseAccess() as db:
                if trackid is None:
                    abort(HTTPStatus.BAD_REQUEST, description="Invalid or missing track id")
                try:
                    add_track_to_queue(db.get_track_by_id(trackid))
                except NotFoundException:
                    abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
        return ('', HTTPStatus.NO_CONTENT)


def add_track_to_queue(track: Track):
    has_artwork = (track.ArtworkPath or track.ArtworkBlob)
    artwork_uri = url_for('get_artwork', trackid=track.Id) if has_artwork else None
    app.player.add_to_queue(track.Filepath, track.Id, track.Artist, track.Title, artwork_uri)


@app.route("/scanner/scan", methods=['POST'])
def start_scan():
    data = request.get_json()
    if data is None:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    subdir = data.get('dir')
    scandir = config.music_dir if (subdir is None) else os.path.join(config.music_dir, subdir)
    # TODO: Error checking on scandir
    app.work_queue.put((WorkRequests.ScanDirectory, scandir))
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/scanner/tidy", methods=['POST'])
def start_tidy():
    app.work_queue.put((WorkRequests.DeleteMissingTracks, ))
    app.work_queue.put((WorkRequests.DeleteAlbumsWithoutTracks, ))
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

if __name__ == '__main__':
    args = parse_args()

    if args.doctest:
        import doctest
        doctest.testmod()
    else:
        logging.basicConfig(level=logging.DEBUG)
        config = Config(args.config)
        db = Database()  # pre-create tables
        app.piju_config = config
        app.work_queue = Queue()
        app.worker = WorkerThread(app.work_queue)
        app.worker.start()
        app.player = MusicPlayer(mp3audiodevice=args.mp3audiodevice)
        app.api_version_string = '5.1'
        app.download_history = DownloadHistory()
        # macOS: Need to disable AirPlay Receiver for listening on 0.0.0.0 to work
        # see https://developer.apple.com/forums/thread/682332
        app.run(use_reloader=False, host='0.0.0.0', threaded=True)
