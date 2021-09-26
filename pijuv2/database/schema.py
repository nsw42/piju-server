from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


album_genre_association_table = Table('association', Base.metadata,
                                      Column('genre_id', Integer, ForeignKey('Genres.Id')),
                                      Column('album_id', Integer, ForeignKey('Albums.Id')))


class Genre(Base):
    __tablename__ = 'Genres'

    Id = Column(Integer, primary_key=True)
    Name = Column(String)
    Albums = relationship("Album",
                          secondary=album_genre_association_table,
                          back_populates="Genres")


class Album(Base):
    __tablename__ = 'Albums'

    Id = Column(Integer, primary_key=True)
    Artist = Column(String)
    Title = Column(String)
    VolumeCount = Column(Integer)
    MusicBrainzAlbumId = Column(String)
    MusicBrainzAlbumArtistId = Column(String)
    ReleaseYear = Column(Integer)
    Tracks = relationship("Track")
    Genres = relationship("Genre",
                          secondary=album_genre_association_table,
                          back_populates="Albums")


class Track(Base):
    __tablename__ = 'Tracks'

    Id = Column(Integer, primary_key=True)
    Filepath = Column(String)
    Title = Column(String)
    Duration = Column(Integer)
    Composer = Column(String)
    Artist = Column(String)
    Genre = Column(Integer, ForeignKey("Genres.Id"))
    VolumeNumber = Column(Integer)
    TrackCount = Column(Integer)
    TrackNumber = Column(Integer)
    ReleaseDate = Column(DateTime)
    MusicBrainzTrackId = Column(String)
    MusicBrainzArtistId = Column(String)
    Album = Column(Integer, ForeignKey("Albums.Id"))
    ArtworkPath = Column(String)  # either this or the next will be populated
    ArtworkBlob = Column(LargeBinary)
    ArtworkWidth = Column(Integer)
    ArtworkHeight = Column(Integer)
