import logging
from typing import List

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool

from .schema import Base, Album, Genre, Track


FILENAME = 'file.db'


class NotFoundException(Exception):
    pass


class Database():
    def __init__(self):
        self.engine = create_engine('sqlite:///' + FILENAME, poolclass=QueuePool)
        self.session = scoped_session(sessionmaker(bind=self.engine))

        # ensure tables exist
        Base.metadata.create_all(self.engine)

        self.session.commit()

    def commit(self):
        self.session.commit()

    def ensure_album_exists(self, albumref: Album):
        """
        Ensure the given album reference is present in the database,
        and return a fully populated object.
        """
        res = self.session.query(Album).filter(
            Album.Title == albumref.Title,
            Album.Artist == albumref.Artist
        )
        # TODO: use res.one_or_none() ??
        count = res.count()
        if count == 0:
            # Artist does not exist
            self.session.add(albumref)
            self.session.commit()
            self.session.refresh(albumref)
            return albumref
        elif count == 1:
            album = res.first()
            if (album.ReleaseYear is None) or (albumref.ReleaseYear is not None
                                               and album.ReleaseYear < albumref.ReleaseYear):
                album.ReleaseYear = albumref.ReleaseYear
                self.session.commit()
            return album
        else:
            logging.fatal("Multiple results found for an album reference")
            assert False

    def ensure_genre_exists(self, genre_name: str) -> Genre:
        """
        Ensure the given genre exists
        """
        res = self.session.query(Genre).filter(
            Genre.Name == genre_name
        )
        # TODO: use res.one_or_none() ??
        count = res.count()
        if count == 0:
            genre = Genre(Name=genre_name)
            self.session.add(genre)
            self.session.commit()
            self.session.refresh(genre)
            return genre
        elif count == 1:
            return res.first()
        else:
            logging.fatal("Multiple results found for a genre")
            assert False

    def ensure_track_exists(self, trackref: Track) -> Track:
        """
        Return the Id for the given Track reference
        Also looks up trackref.Genre in the database if it's a string, and replaces it with a fk to the genre table
        """
        if isinstance(trackref.Genre, str):
            trackref.Genre = self.ensure_genre_exists(trackref.Genre).Id
        res = self.session.query(Track).filter(
            Track.Title == trackref.Title,
            Track.Duration == trackref.Duration,
            Track.Artist == trackref.Artist,
            Track.VolumeNumber == trackref.VolumeNumber,
            Track.TrackNumber == trackref.TrackNumber,
            Track.ReleaseDate == trackref.ReleaseDate,
            Track.MusicBrainzTrackId == trackref.MusicBrainzTrackId,
            Track.MusicBrainzArtistId == trackref.MusicBrainzArtistId
        )
        count = res.count()
        if count == 0:
            # Track does not exist
            self.session.add(trackref)
            self.session.commit()
            self.session.refresh(trackref)
            return trackref
        elif count == 1:
            return res.first()
        else:
            logging.fatal("Multiple results found for a track reference")
            assert False

    def get_album_by_id(self, albumid: int):
        """
        Return the Album object for a given id.
        Raises NotFoundException for an unknown id
        """
        res = self.session.query(Album).filter(
            Album.Id == albumid
        )
        count = res.count()
        if count == 0:
            raise NotFoundException()
        elif count == 1:
            return res.first()
        else:
            logging.fatal("Multiple results for a given album id")
            assert False

    def get_all_albums(self) -> List[Album]:
        """
        Primarily for debugging
        """
        result = self.session.execute(select(Album).order_by(Album.Artist, Album.Title))
        return result.scalars().all()

    def get_all_genres(self):
        """
        Primarily for debugging
        """
        result = self.session.execute(select(Genre).order_by(Genre.Name))
        return result.scalars().all()

    def get_all_tracks(self):
        """
        Primarily for debugging
        """
        result = self.session.execute(select(Track).order_by(Track.Artist, Track.Album, Track.TrackNumber))
        return result.scalars().all()

    def get_genre_by_id(self, genreid: int):
        """
        Return the Genre object for a given id.
        Raises NotFoundException for an unknown id
        """
        res = self.session.query(Genre).filter(
            Genre.Id == genreid
        )
        count = res.count()
        if count == 0:
            raise NotFoundException()
        elif count == 1:
            return res.first()
        else:
            logging.fatal("Multiple results for a given genre id")
            assert False

    def get_track_by_id(self, trackid: int):
        """
        Return the Track object for a given id.
        Raises NotFoundException for an unknown id
        """
        res = self.session.query(Track).filter(
            Track.Id == trackid
        )
        count = res.count()
        if count == 0:
            raise NotFoundException()
        elif count == 1:
            return res.first()
        else:
            logging.fatal("Multiple results for a given track id")
            assert False

    def get_nr_tracks(self):
        return self.session.query(Track).with_entities(func.count(Track.Id)).scalar()


class DatabaseAccess:
    def __init__(self):
        self.db = Database()

    def __enter__(self):
        return self.db

    def __exit__(self, type, value, traceback):
        self.db.commit()
        del self.db
