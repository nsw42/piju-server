import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import schema


class Database():
    def __init__(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.session = Session(self.engine)

        # ensure tables exist
        schema.Base.metadata.create_all(self.engine)

    def album(self, albumref: schema.Album):
        """
        Return the Id for the given Album reference
        """
        res = self.session.query(schema.Album).filter(
            schema.Album.Title == albumref.Title,
            schema.Album.Artist == albumref.Artist
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

    def track(self, trackref: schema.Track):
        """
        Return the Id for the given Track reference
        """
        res = self.session.query(schema.Track).filter(
            schema.Track.Title == trackref.Title,
            schema.Track.Duration == trackref.Title,
            schema.Track.Artist == trackref.Title,
            schema.Track.VolumeNumber == trackref.VolumeNumber,
            schema.Track.TrackNumber == trackref.TrackNumber,
            schema.Track.ReleaseDate == trackref.ReleaseDate,
            schema.Track.MusicBrainzTrackId == trackref.MusicBrainzTrackId,
            schema.Track.MusicBrainzArtistId == trackref.MusicBrainzArtistId
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
