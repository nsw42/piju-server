from queue import Queue
import json

from flask import Flask, abort

from ..database.database import Database, DatabaseAccess, NotFoundException
from .workqueue import WorkRequests
from .workthread import WorkerThread

app = Flask(__name__)
music_dir = '/Users/Shared/iTunes Media/Music'


@app.route("/")
def current_status():
    with DatabaseAccess() as db:
        rtn = {
            'WorkerStatus': app.worker.current_status,
            'NumberTracks': db.get_nr_tracks(),
        }
    return json.dumps(rtn)


def album_json(album, include_tracks):
    rtn = {
        'link': '/albums/%u' % album.Id,
        'artist': album.Artist,
        'title': album.Title,
    }
    if include_tracks:
        tracks = list(album.Tracks)
        tracks = sorted(tracks, key=lambda track: track.TrackNumber if track.TrackNumber else 0)
        rtn['tracks'] = ['/tracks/%u' % track.Id for track in tracks]
    return rtn


@app.route("/albums")
def get_all_albums():
    with DatabaseAccess() as db:
        rtn = []
        for album in db.get_all_albums():
            rtn.append(album_json(album, include_tracks=False))
        return json.dumps(rtn)


@app.route("/albums/<albumid>")
def get_album(albumid):
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException:
            abort(404, description="Unknown album id")
        return json.dumps(album_json(album, include_tracks=True))


@app.route("/tracks")
def get_all_tracks():
    abort(404)  # TODO


@app.route("/tracks/<trackid>")
def get_track(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(404, description="Unknown track id")
        rtn = {
            'id': track.Id,
            'artist': track.Artist,
            'title': track.Title,
            'genre': track.Genre,
            'tracknumber': track.TrackNumber,
            'trackcount': track.TrackCount,
            'album': '/albums/%u' % track.Album,
        }
        return json.dumps(rtn)


if __name__ == '__main__':
    db = Database()  # pre-create tables
    queue = Queue()
    queue.put((WorkRequests.ScanDirectory, music_dir))
    app.worker = WorkerThread(queue)
    app.worker.start()
    app.run(debug=True, use_reloader=False)
