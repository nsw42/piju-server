import pathlib

from ..database.database import Database
from ..database.schema import Album, Track
from .m4a import scan_m4a
from .mp3 import scan_mp3


# TODO: This is starting to feel like it belongs in the database class
def set_cross_refs(db: Database, track: Track, albumref: Album):
    editing_track = (track.Id is not None)
    track = db.ensure_track_exists(track)
    # ensure_track_exists() ensures that track.Genre is either None or a genre id
    album = db.ensure_album_exists(albumref)
    track.Album = album.Id
    # setting track.Album automatically creates the back-reference in album.Tracks,
    # and adding genre to album.Genres also adds the album to the genre.
    # However, if we only ever add to it, we can still have a problem that album.Genres
    # contains a genre that is no longer relevant - if all tracks in the album have
    # changed genre.
    if editing_track:
        genre_ids = set([track.Genre for track in album.Tracks])
        genres = [db.get_genre_by_id(genreid) for genreid in genre_ids]
        album.Genres = genres
    else:
        genre = db.get_genre_by_id(track.Genre) if track.Genre else None
        if genre and genre not in album.Genres:
            album.Genres.append(genre)


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
