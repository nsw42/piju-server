import pathlib

from ..database.database import Database
from ..database.schema import Album, Track
from .m4a import scan_m4a
from .mp3 import scan_mp3


def scan_directory(basedir: pathlib.Path, db: Database):
    import threading
    print("scan_directory: thread %s" % threading.get_native_id())

    def set_cross_refs(track: Track, albumref: Album):
        db.track(track)  # updates track.Id
        track.Album = db.album(albumref)  # also updates albumref.Id and adds track to albumref.Tracks

    for path in basedir.rglob('*.mp3'):
        track, albumref = scan_mp3(path)
        set_cross_refs(track, albumref)

    for path in basedir.rglob('*.m4a'):
        track, albumref = scan_m4a(path)
        set_cross_refs(track, albumref)
