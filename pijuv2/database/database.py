import logging

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from .schema import Base, Album, Track


class NotFoundException(Exception):
    pass


class Database():
    def __init__(self):
        self.engine = create_engine('sqlite:///file.db')
        self.session = Session(self.engine)

        # ensure tables exist
        Base.metadata.create_all(self.engine)

        self.session.commit()

    def __del__(self):
        self.commit()

    def commit(self):
        self.session.commit()

    def album(self, albumref: Album):
        """
        Return the Id for the given Album reference
        """
        res = self.session.query(Album).filter(
            Album.Title == albumref.Title,
            Album.Artist == albumref.Artist
        )
        count = res.count()
        if count == 0:
            # Artist does not exist
            self.session.add(albumref)
            self.session.commit()
            self.session.refresh(albumref)
        elif count == 1:
            albumref.Id = res.first().Id
        else:
            logging.fatal("Multiple results found for an album reference")
            assert False
        return albumref.Id

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

    def track(self, trackref: Track):
        """
        Return the Id for the given Track reference
        """
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
        elif count == 1:
            trackref.Id = res.first().Id
        else:
            logging.fatal("Multiple results found for a track reference")
            assert False
        return trackref.Id

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

    def get_all_albums(self):
        """
        Primarily for debugging
        """
        result = self.session.execute(select(Album).order_by(Album.Artist, Album.Title))
        return result.scalars().all()

    def get_all_tracks(self):
        """
        Primarily for debugging
        """
        result = self.session.execute(select(Track).order_by(Track.Artist, Track.Album, Track.TrackNumber))
        return result.scalars().all()


class DatabaseAccess:
    def __init__(self):
        self.db = Database()

    def __enter__(self):
        return self.db

    def __exit__(self, type, value, traceback):
        self.db.commit()
