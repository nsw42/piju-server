from functools import wraps
from http import HTTPStatus
import json
import mimetypes
from pathlib import Path
from queue import Queue

from flask import abort, Flask, request, Response, url_for

from ..database.database import Database, DatabaseAccess, NotFoundException
from ..database.schema import Album, Genre, Track
from ..player.player import MusicPlayer
from .workqueue import WorkRequests
from .workthread import WorkerThread

app = Flask(__name__)
music_dir = '/Users/Shared/iTunes Media/Music'

mimetypes.init()


def returns_json(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        r = f(*args, **kwargs)
        return Response(r, mimetype='application/json')
    return decorated_function


def json_album(album: Album, include_tracks: bool):
    tracks = list(album.Tracks)
    tracks = sorted(tracks, key=lambda track: track.TrackNumber if track.TrackNumber else 0)
    for track in tracks:
        if track.ArtworkPath or track.ArtworkBlob:
            artwork = url_for('get_artwork', trackid=track.Id)
            break
    else:
        artwork = None
    rtn = {
        'link': url_for('get_album', albumid=album.Id),
        'artist': album.Artist,
        'title': album.Title,
        'artwork': artwork,
        'genres': [url_for('get_genre', genreid=genre.Id) for genre in album.Genres],
    }
    if include_tracks:
        rtn['tracks'] = [url_for('get_track', trackid=track.Id) for track in tracks]
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
    rtn = {
        'link': url_for('get_track', trackid=track.Id),
        'artist': track.Artist,
        'title': track.Title,
        'genre': track.Genre,
        'tracknumber': track.TrackNumber,
        'trackcount': track.TrackCount,
        'album': url_for('get_album', albumid=track.Album) if track.Album else '',
        'artwork': url_for('get_artwork', trackid=track.Id) if (track.ArtworkPath or track.ArtworkBlob) else None,
    }
    return rtn


@app.route("/")
@returns_json
def current_status():
    with DatabaseAccess() as db:
        track = db.get_track_by_id(app.player.current_track_id) if app.player.current_track_id else None
        rtn = {
            'WorkerStatus': app.worker.current_status,
            'PlayerStatus': str(app.player.status),
            'CurrentTrack': {} if track is None else json_track(track),
            'NumberTracks': db.get_nr_tracks(),
        }
    return json.dumps(rtn)


@app.route("/albums/")
@returns_json
def get_all_albums():
    with DatabaseAccess() as db:
        rtn = []
        for album in db.get_all_albums():
            rtn.append(json_album(album, include_tracks=False))
        return json.dumps(rtn)


@app.route("/albums/<albumid>")
@returns_json
def get_album(albumid):
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown album id")
        return json.dumps(json_album(album, include_tracks=True))


@app.route("/genres/")
@returns_json
def get_all_genres():
    with DatabaseAccess() as db:
        rtn = []
        for genre in db.get_all_genres():
            rtn.append(json_genre(genre, include_albums=False))
        return json.dumps(rtn)


@app.route("/genres/<genreid>")
@returns_json
def get_genre(genreid):
    with DatabaseAccess() as db:
        try:
            genre = db.get_genre_by_id(genreid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown genre id")
        return json.dumps(json_genre(genre, include_albums=True))


@app.route("/tracks/")
@returns_json
def get_all_tracks():
    with DatabaseAccess() as db:
        rtn = []
        for track in db.get_all_tracks():
            rtn.append(json_track(track))
        return json.dumps(rtn)


@app.route("/tracks/<trackid>")
@returns_json
def get_track(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
        return json.dumps(json_track(track))


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
            return Response(data, mimetype=mime)

        elif track.ArtworkBlob:
            if track.ArtworkBlob[:3] == b'\xff\xd8\xff':
                mime = mimetypes.types_map['.jpg']
            elif track.ArtworkBlob[:8] == b'\x89\x50\x4e\x47\x0d\x0a\x1a\x0a':
                mime = mimetypes.types_map['.png']
            else:
                abort(500, description="Unknown mime type")

            return Response(track.ArtworkBlob, mimetype=mime)

        else:
            abort(HTTPStatus.NOT_FOUND, description="Unknown track id")


@app.route("/player/play", methods=['POST'])
def update_player_play():
    data = request.get_json()
    with DatabaseAccess() as db:
        albumid = data.get('album')
        trackid = data.get('track')
        if albumid:
            try:
                albumid = db.get_album_by_id(albumid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description="Unknown album id")
            queue = list(sorted(albumid.Tracks, key=lambda track: track.TrackNumber if track.TrackNumber else 0))
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


if __name__ == '__main__':
    db = Database()  # pre-create tables
    queue = Queue()
    queue.put((WorkRequests.ScanDirectory, music_dir))
    app.worker = WorkerThread(queue)
    app.worker.start()
    app.player = MusicPlayer()
    app.run(debug=True, use_reloader=False)
