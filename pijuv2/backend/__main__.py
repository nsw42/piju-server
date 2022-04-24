from argparse import ArgumentParser
import gzip
from http import HTTPStatus
import json
import mimetypes
import os.path
from pathlib import Path
import resource
from queue import Queue
from typing import List

from flask import abort, Flask, make_response, request, Response, url_for

from ..database.database import Database, DatabaseAccess, NotFoundException
from ..database.schema import Album, Genre, Playlist, PlaylistEntry, Track
from ..player.mpyg321 import PlayerStatus
from ..player.player import MusicPlayer
from .config import Config
from .workqueue import WorkRequests
from .workthread import WorkerThread


class InformationLevel:
    NoInfo = 0
    Links = 1
    AllInfo = 2

    @staticmethod
    def from_string(info: str, default: 'InformationLevel' = Links):
        info = info.lower()
        if info == 'none':
            return InformationLevel.NoInfo
        elif info == 'all':
            return InformationLevel.AllInfo
        elif info == 'links':
            return InformationLevel.Links
        else:
            return default


app = Flask(__name__)

mimetypes.init()


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
    tracks = sorted(tracks, key=lambda track: track.TrackNumber if track.TrackNumber else 0)
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
        'artwork': {
            'link': artwork_uri,
            'width': artwork_width,
            'height': artwork_height
        },
        'genres': [url_for('get_genre', genreid=genre.Id) for genre in album.Genres],
    }
    if include_tracks == InformationLevel.Links:
        rtn['tracks'] = [url_for('get_track', trackid=track.Id) for track in tracks]
    elif include_tracks == InformationLevel.AllInfo:
        rtn['tracks'] = [json_track(track) for track in tracks]
    return rtn


def json_genre(genre: Genre, include_albums: InformationLevel, include_playlists: InformationLevel):
    rtn = {
        'link': url_for('get_genre', genreid=genre.Id),
        'name': genre.Name,
    }
    if include_albums == InformationLevel.Links:
        rtn['albums'] = [url_for('get_album', albumid=album.Id) for album in genre.Albums]
    elif include_albums == InformationLevel.AllInfo:
        rtn['albums'] = [json_album(album, include_tracks=InformationLevel.AllInfo) for album in genre.Albums]
    if include_playlists == InformationLevel.Links:
        rtn['playlists'] = [url_for('one_playlist', playlistid=playlist.Id) for playlist in genre.Playlists]
    elif include_playlists == InformationLevel.AllInfo:
        rtn['playlists'] = [json_playlist(playlist, include_tracks=InformationLevel.AllInfo)
                            for playlist in genre.Playlists]
    return rtn


def json_playlist(playlist: Playlist, include_tracks: InformationLevel):
    entries = list(playlist.Entries)
    rtn = {
        'link': url_for('one_playlist', playlistid=playlist.Id),
        'title': playlist.Title,
        'genres': [url_for('get_genre', genreid=genre.Id) for genre in playlist.Genres],
    }
    if include_tracks == InformationLevel.Links:
        rtn['tracks'] = [url_for('get_track', trackid=entry.TrackId) for entry in entries]
    elif include_tracks == InformationLevel.AllInfo:
        rtn['tracks'] = [json_track(entry.Track) for entry in entries]
    return rtn


def json_track(track: Track):
    has_artwork = track.ArtworkPath or track.ArtworkBlob
    rtn = {
        'link': url_for('get_track', trackid=track.Id),
        'artist': track.Artist,
        'title': track.Title,
        'genre': track.Genre,
        'tracknumber': track.TrackNumber,
        'trackcount': track.TrackCount,
        'album': url_for('get_album', albumid=track.Album) if track.Album else '',
        'artwork': url_for('get_artwork', trackid=track.Id) if has_artwork else None,
        'artworkinfo': url_for('get_artwork_info', trackid=track.Id) if has_artwork else None,
    }
    return rtn


PLAYER_STATUS_REPRESENTATION = {
    PlayerStatus.INSTANCIATED: "stopped",
    PlayerStatus.PLAYING: "playing",
    PlayerStatus.PAUSED: "paused",
    PlayerStatus.RESUMING: "playing",
    PlayerStatus.STOPPING: "stopped",
    PlayerStatus.QUITTED: "stopped"
}


def build_playlist_from_api_data(db: Database, request) -> Playlist:
    data = request.get_json()
    title = data.get('title')
    trackids = extract_ids(data.get('tracks', []))
    m3u = data.get('m3u')
    if title in (None, ""):
        abort(HTTPStatus.BAD_REQUEST, "Playlist title must be specified")
    if (not trackids) and (not m3u):
        abort(HTTPStatus.BAD_REQUEST, "Either a list of tracks or an m3u playlist must be specified")
    if (trackids) and (m3u):
        abort(HTTPStatus.BAD_REQUEST, "Only one of a list of tracks and an m3u playlist is permitted")
    if m3u:
        m3u = m3u.splitlines()
        m3u = [line for line in m3u if line and not line.startswith('#')]
        tracks = []
        for filepath in m3u:
            try:
                fullpath = app.piju_config.music_dir / filepath
                track = db.get_track_by_filepath(str(fullpath))
                tracks.append(track)
            except NotFoundException:
                print(f"Could not find a track at {filepath} - looked in {fullpath}")
    else:
        if None in trackids:
            abort(HTTPStatus.BAD_REQUEST, "Invalid track reference")
        try:
            tracks = [db.get_track_by_id(trackid) for trackid in trackids]
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
    playlist_entries = []
    for index, track in enumerate(tracks):
        playlist_entries.append(PlaylistEntry(PlaylistIndex=index, TrackId=track.Id))
    genres = set(track.Genre for track in tracks if track.Genre is not None)
    genres = list(genres)
    genres = [db.get_genre_by_id(genre) for genre in genres]
    return Playlist(Title=title, Entries=playlist_entries, Genres=genres)


def extract_id(uri_or_id):
    """
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


@app.route("/")
def current_status():
    with DatabaseAccess() as db:
        track = db.get_track_by_id(app.player.current_track_id) if app.player.current_track_id else None
        rtn = {
            'WorkerStatus': app.worker.current_status,
            'PlayerStatus': PLAYER_STATUS_REPRESENTATION.get(app.player.status, "stopped"),
            'PlayerVolume': app.player.current_volume,
            'CurrentTrack': {} if track is None else json_track(track),
            'NumberAlbums': db.get_nr_albums(),
            'NumberTracks': db.get_nr_tracks(),
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
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
        return gzippable_jsonify(json_track(track))


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


def play_track_list(tracks: List[Track], start_at_track_id: int):
    if start_at_track_id is None:
        play_from_index = 0
    else:
        track_ids = [track.Id for track in tracks]
        try:
            play_from_index = track_ids.index(start_at_track_id)
        except ValueError:
            abort(HTTPStatus.BAD_REQUEST, "Requested track is not in the specified album")
    app.player.set_queue(tracks)
    app.player.play_from_queue_index(play_from_index)


@app.route("/player/play", methods=['POST'])
def update_player_play():
    data = request.get_json()
    if not data:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    with DatabaseAccess() as db:
        albumid = extract_id(data.get('album'))
        playlistid = extract_id(data.get('playlist'))
        trackid = extract_id(data.get('track'))
        if (albumid is not None) and (playlistid is not None):
            abort(HTTPStatus.BAD_REQUEST, "Album and playlist must not both be specified")

        if albumid is not None:
            try:
                album = db.get_album_by_id(albumid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown album id")

            tracks = list(sorted(album.Tracks, key=lambda track: track.TrackNumber if track.TrackNumber else 0))
            play_track_list(tracks, trackid)

        elif playlistid is not None:
            try:
                playlist = db.get_playlist_by_id(playlistid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
            play_track_list([entry.Track for entry in playlist.Entries], trackid)

        elif trackid:
            try:
                track = db.get_track_by_id(trackid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
            app.player.play_song(track.Filepath)

        else:
            abort(HTTPStatus.BAD_REQUEST, description='Album, playlist or track must be specified')
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/pause", methods=['POST'])
def update_player_pause():
    app.player.pause()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/resume", methods=['POST'])
def update_player_resume():
    app.player.resume()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/next", methods=['POST'])
def update_player_next():
    app.player.next()
    return ('', HTTPStatus.NO_CONTENT)


@app.route("/player/previous", methods=['POST'])
def update_player_prev():
    app.player.prev()
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
        try:
            volume = data.get('volume')
            volume = int(volume)
            app.player.volume(volume)
            return ('', HTTPStatus.NO_CONTENT)
        except (AttributeError, KeyError, ValueError):
            abort(HTTPStatus.BAD_REQUEST, description='Volume must be specified and numeric')


@app.route("/playlists/", methods=['GET', 'POST'])
def playlists():
    if request.method == 'GET':
        with DatabaseAccess() as db:
            rtn = []
            for playlist in db.get_all_playlists():
                rtn.append(json_playlist(playlist, include_tracks=InformationLevel.NoInfo))
            return gzippable_jsonify(rtn)
    elif request.method == 'POST':
        with DatabaseAccess() as db:
            playlist = build_playlist_from_api_data(db, request)
            db.create_playlist(playlist)
            return str(playlist.Id)


@app.route("/playlists/<playlistid>", methods=['DELETE', 'GET', 'PUT'])
def one_playlist(playlistid):
    if request.method == 'GET':
        track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
        with DatabaseAccess() as db:
            try:
                playlist = db.get_playlist_by_id(playlistid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
            return gzippable_jsonify(json_playlist(playlist, include_tracks=track_info))
    elif request.method == 'PUT':
        with DatabaseAccess() as db:
            playlist = build_playlist_from_api_data(db, request)
            playlist = db.update_playlist(playlistid, playlist)
            return str(playlist.Id)
    elif request.method == 'DELETE':
        with DatabaseAccess() as db:
            try:
                db.delete_playlist(playlistid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
            return ('', HTTPStatus.NO_CONTENT)


@app.route("/scanner/scan", methods=['POST'])
def start_scan():
    data = request.get_json()
    subdir = data.get('dir')
    scandir = config.music_dir if (subdir is None) else os.path.join(config.music_dir, subdir)
    # TODO: Error checking on scandir
    app.queue.put((WorkRequests.ScanDirectory, scandir))
    return ('', HTTPStatus.NO_CONTENT)


def parse_args():
    parser = ArgumentParser()
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


if __name__ == '__main__':
    args = parse_args()

    if args.doctest:
        import doctest
        doctest.testmod()
    else:
        resource.setrlimit(resource.RLIMIT_NOFILE, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
        config = Config(args.config)
        db = Database()  # pre-create tables
        app.piju_config = config
        app.queue = Queue()
        app.queue.put((WorkRequests.ScanDirectory, config.music_dir))
        app.worker = WorkerThread(app.queue)
        app.worker.start()
        app.player = MusicPlayer()
        # macOS: Need to disable AirPlay Receiver for listening on 0.0.0.0 to work
        # see https://developer.apple.com/forums/thread/682332
        app.run(use_reloader=False, host='0.0.0.0')
