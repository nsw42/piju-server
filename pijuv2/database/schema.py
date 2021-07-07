from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Album(Base):
    __tablename__ = 'Albums'

    Id = Column(Integer, primary_key=True)
    Artist = Column(String)
    Title = Column(String)
    VolumeCount = Column(Integer)
    MusicBrainzAlbumId = Column(String)
    MusicBrainzAlbumArtistId = Column(String)
    Tracks = relationship("Track")


class Track(Base):
    __tablename__ = 'Tracks'

    Id = Column(Integer, primary_key=True)
    Filepath = Column(String)
    Title = Column(String)
    Duration = Column(Integer)
    Composer = Column(String)
    Artist = Column(String)
    Genre = Column(String)
    VolumeNumber = Column(Integer)
    TrackCount = Column(Integer)
    TrackNumber = Column(Integer)
    ReleaseDate = Column(DateTime)
    MusicBrainzTrackId = Column(String)
    MusicBrainzArtistId = Column(String)
    Album = Column(Integer, ForeignKey("Albums.Id"))
    ArtworkPath = Column(String)  # either this or the next will be populated
    ArtworkBlob = Column(LargeBinary)
