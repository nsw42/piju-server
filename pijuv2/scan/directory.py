import pathlib

from ..database.database import Database
from ..database.schema import Album, Track
from .m4a import scan_m4a
from .mp3 import scan_mp3


# TODO: This is starting to feel like it belongs in the database class
def set_cross_refs(db: Database, track: Track, albumref: Album):
    track = db.ensure_track_exists(track)
    # ensure_track_exists() ensures that track.Genre is either None or a genre id
    album = db.ensure_album_exists(albumref)
    genre = db.get_genre_by_id(track.Genre) if track.Genre else None
    track.Album = album.Id
    if genre and genre not in album.Genres:
        album.Genres.append(genre)
    # setting track.Album automatically creates the back-reference in album.Tracks,
    # and adding genre to album.Genres also adds the album to the genre.


def scan_directory(basedir: pathlib.Path, db: Database, limit: int = None):
    i = 0
    for (pattern, scanner) in [('*.mp3', scan_mp3),
                               ('*.m4a', scan_m4a)]:
        for path in basedir.rglob(pattern):
            existing_track = db.get_track_by_filepath(str(path))
            track, albumref = scanner(path)
            if existing_track is not None:
                track.Id = existing_track.Id
            if track:
                set_cross_refs(db, track, albumref)
            i += 1
            if (limit is not None) and (i >= limit):
                return
