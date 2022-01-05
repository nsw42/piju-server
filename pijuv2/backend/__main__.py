from argparse import ArgumentParser
from http import HTTPStatus
import mimetypes
from pathlib import Path
import resource
from queue import Queue

from flask import abort, Flask, jsonify, request, Response, url_for

from ..database.database import Database, DatabaseAccess, NotFoundException
from ..database.schema import Album, Genre, Track
from ..player.mpyg321 import PlayerStatus
from ..player.player import MusicPlayer
from .config import Config
from .workqueue import WorkRequests
from .workthread import WorkerThread


class TrackInformationLevel:
    NoTracks = 0
    TrackLinks = 1
    AllTrackInfo = 2


app = Flask(__name__)

mimetypes.init()


def json_album(album: Album, include_tracks: TrackInformationLevel):
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
    if include_tracks == TrackInformationLevel.TrackLinks:
        rtn['tracks'] = [url_for('get_track', trackid=track.Id) for track in tracks]
    elif include_tracks == TrackInformationLevel.AllTrackInfo:
        rtn['tracks'] = [json_track(track) for track in tracks]
    return rtn


def json_genre(genre: Genre, include_albums: bool):
    rtn = {
        'link': url_for('get_genre', genreid=genre.Id),
        'name': genre.Name,
    }
    if include_albums:
        rtn['albums'] = [url_for('get_album', albumid=album.Id) for album in genre.Albums]
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


@app.route("/")
def current_status():
    with DatabaseAccess() as db:
        track = db.get_track_by_id(app.player.current_track_id) if app.player.current_track_id else None
        rtn = {
            'WorkerStatus': app.worker.current_status,
            'PlayerStatus': PLAYER_STATUS_REPRESENTATION.get(app.player.status, "stopped"),
            'PlayerVolume': app.player.current_volume,
            'CurrentTrack': {} if track is None else json_track(track),
            'NumberTracks': db.get_nr_tracks(),
        }
    return jsonify(rtn)


@app.route("/albums/")
def get_all_albums():
    with DatabaseAccess() as db:
        rtn = []
        for album in db.get_all_albums():
            rtn.append(json_album(album, include_tracks=TrackInformationLevel.NoTracks))
        return jsonify(rtn)


@app.route("/albums/<albumid>")
def get_album(albumid):
    track_info = request.args.get('tracks', '').lower()
    if track_info == 'none':
        track_info = TrackInformationLevel.NoTracks
    elif track_info == 'all':
        track_info = TrackInformationLevel.AllTrackInfo
    else:
        track_info = TrackInformationLevel.TrackLinks
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown album id")
        return jsonify(json_album(album, include_tracks=track_info))


@app.route("/genres/")
def get_all_genres():
    with DatabaseAccess() as db:
        rtn = []
        for genre in db.get_all_genres():
            rtn.append(json_genre(genre, include_albums=False))
        return jsonify(rtn)


@app.route("/genres/<genreid>")
def get_genre(genreid):
    with DatabaseAccess() as db:
        try:
            genre = db.get_genre_by_id(genreid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown genre id")
        return jsonify(json_genre(genre, include_albums=True))


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
        return jsonify(rtn)


@app.route("/tracks/<trackid>")
def get_track(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
        return jsonify(json_track(track))


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
        return jsonify(rtn)


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


@app.route("/player/play", methods=['POST'])
def update_player_play():
    data = request.get_json()
    with DatabaseAccess() as db:
        albumid = extract_id(data.get('album'))
        trackid = extract_id(data.get('track'))
        if albumid is not None:
            try:
                album = db.get_album_by_id(albumid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown album id")
            queue = list(sorted(album.Tracks, key=lambda track: track.TrackNumber if track.TrackNumber else 0))
            app.player.set_queue(queue)
            if trackid is None:
                play_from_index = 0
            else:
                track_ids = [track.Id for track in queue]
                try:
                    play_from_index = track_ids.index(trackid)
                except ValueError:
                    abort(HTTPStatus.BAD_REQUEST, "Requested track is not in the specified album")
            app.player.play_from_queue_index(play_from_index)

        elif trackid:
            try:
                track = db.get_track_by_id(trackid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
            app.player.play_song(track.Filepath)

        else:
            abort(HTTPStatus.BAD_REQUEST, description='Album or track must be specified')
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
        queue = Queue()
        queue.put((WorkRequests.ScanDirectory, config.music_dir))
        app.worker = WorkerThread(queue)
        app.worker.start()
        app.player = MusicPlayer()
        # macOS: Need to disable AirPlay Receiver for listening on 0.0.0.0 to work
        # see https://developer.apple.com/forums/thread/682332
        app.run(use_reloader=False, host='0.0.0.0')
