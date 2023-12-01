from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Table
from sqlalchemy import event
from sqlalchemy.orm import declarative_base, relationship, Session

# IMPORTANT: If changing the schema, be sure to create the alembic revision to support the migration of data
# Run:
#   $ DB_FILE=file.db alembic revision -m "One line description of change" --autogenerate

Base = declarative_base()


album_genre_association_table = Table('association', Base.metadata,
                                      Column('genre_id', Integer, ForeignKey('Genres.Id')),
                                      Column('album_id', Integer, ForeignKey('Albums.Id')))


playlist_genre_association_table = Table('playlist_to_genres', Base.metadata,
                                         Column('genre_id', Integer, ForeignKey('Genres.Id')),
                                         Column('playlist_id', Integer, ForeignKey('Playlists.Id')))


class PlaylistEntry(Base):
    __tablename__ = 'playlist_to_track'

    Id = Column(Integer, primary_key=True)
    PlaylistId = Column(ForeignKey('Playlists.Id'))
    TrackId = Column(ForeignKey('Tracks.Id'))
    PlaylistIndex = Column(Integer)
    Track = relationship("Track")


class Genre(Base):
    __tablename__ = 'Genres'

    Id = Column(Integer, primary_key=True)
    Name = Column(String)
    Albums = relationship("Album",
                          secondary=album_genre_association_table,
                          back_populates="Genres")
    Playlists = relationship("Playlist",
                             secondary=playlist_genre_association_table,
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
    IsCompilation = Column(Boolean)
    Tracks = relationship("Track")
    Genres = relationship("Genre",
                          secondary=album_genre_association_table,
                          back_populates="Albums")


class Playlist(Base):
    __tablename__ = 'Playlists'

    Id = Column(Integer, primary_key=True)
    Title = Column(String)
    Entries = relationship("PlaylistEntry",
                           order_by=PlaylistEntry.__table__.c.PlaylistIndex)
    Genres = relationship("Genre",
                          secondary=playlist_genre_association_table,
                          back_populates="Playlists")


class RadioStation(Base):
    __tablename__ = 'RadioStations'

    Id = Column(Integer, primary_key=True)
    Name = Column(String)
    Url = Column(String)
    ArtworkUrl = Column(String)
    NowPlayingUrl = Column(String)
    NowPlayingJq = Column(String)
    NowPlayingArtworkUrl = Column(String)
    NowPlayingArtworkJq = Column(String)
    SortOrder = Column(Integer)


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
    Artwork = Column(Integer, ForeignKey("Artwork.Id"))
    ArtworkObject = relationship("Artwork", back_populates="Tracks")


class Artwork(Base):
    __tablename__ = 'Artwork'

    Id = Column(Integer, primary_key=True)
    Path = Column(String)  # either this or the next will be populated
    Blob = Column(LargeBinary)
    BlobHash = Column(String)
    Width = Column(Integer)
    Height = Column(Integer)
    Tracks = relationship("Track", back_populates="ArtworkObject", cascade="all, delete")


# Based on
# https://stackoverflow.com/questions/51419186/delete-parent-object-when-all-children-have-been-deleted-in-sqlalchemy
@event.listens_for(Track, 'before_delete')
def delete_unused_artwork(_mapper, _connection, track):
    @event.listens_for(Session, 'after_flush', once=True)
    def act_after_flush(session, _context):
        if track.ArtworkObject and not track.ArtworkObject.Tracks:
            session.delete(track.ArtworkObject)
