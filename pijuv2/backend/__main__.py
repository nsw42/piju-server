import json
import mimetypes
from pathlib import Path
from queue import Queue

from flask import abort, Flask, Response

from ..database.database import Database, DatabaseAccess, NotFoundException
from .workqueue import WorkRequests
from .workthread import WorkerThread

app = Flask(__name__)
music_dir = '/Users/Shared/iTunes Media/Music'

mimetypes.init()


@app.route("/")
def current_status():
    with DatabaseAccess() as db:
        rtn = {
            'WorkerStatus': app.worker.current_status,
            'NumberTracks': db.get_nr_tracks(),
        }
    return json.dumps(rtn)


def album_json(album, include_tracks):
    tracks = list(album.Tracks)
    tracks = sorted(tracks, key=lambda track: track.TrackNumber if track.TrackNumber else 0)
    for track in tracks:
        if track.ArtworkPath or track.ArtworkBlob:
            artwork = '/artwork/%u' % track.Id
            break
    else:
        artwork = None
    rtn = {
        'link': '/albums/%u' % album.Id,
        'artist': album.Artist,
        'title': album.Title,
        'artwork': artwork,
    }
    if include_tracks:
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
            'link': '/tracks/%u' % track.Id,
            'artist': track.Artist,
            'title': track.Title,
            'genre': track.Genre,
            'tracknumber': track.TrackNumber,
            'trackcount': track.TrackCount,
            'album': '/albums/%u' % track.Album,
            'artwork': ('/artwork/%u' % track.Id) if (track.ArtworkPath or track.ArtworkBlob) else None,
        }
        return json.dumps(rtn)


@app.route("/artwork/<trackid>")
def get_artwork(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(404, description="Unknown track id")

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
            abort(404, description="Unknown track id")


if __name__ == '__main__':
    db = Database()  # pre-create tables
    queue = Queue()
    queue.put((WorkRequests.ScanDirectory, music_dir))
    app.worker = WorkerThread(queue)
    app.worker.start()
    app.run(debug=True, use_reloader=False)
