import json
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Table, event
from sqlalchemy.orm import DeclarativeBase, mapped_column, relationship, Session

# IMPORTANT: If changing the schema, be sure to create the alembic revision to support the migration of data
# Run:
#   $ cd pijuv2/database
#   $ DB_FILE=file.db alembic revision -m "One line description of change" --autogenerate


class Base(DeclarativeBase):
    pass


album_genre_association_table = Table('association', Base.metadata,
                                      Column('genre_id', Integer, ForeignKey('Genres.Id')),
                                      Column('album_id', Integer, ForeignKey('Albums.Id')))


playlist_genre_association_table = Table('playlist_to_genres', Base.metadata,
                                         Column('genre_id', Integer, ForeignKey('Genres.Id')),
                                         Column('playlist_id', Integer, ForeignKey('Playlists.Id')))


class PlaylistEntry(Base):
    "A single item in a playlist"
    __tablename__ = 'playlist_to_track'

    Id = mapped_column(Integer, primary_key=True)
    PlaylistId = mapped_column(ForeignKey('Playlists.Id'))
    TrackId = mapped_column(ForeignKey('Tracks.Id'))
    PlaylistIndex = mapped_column(Integer)
    Track = relationship("Track")


class Genre(Base):
    "A collection of albums and playlists that contain items of the same genre"
    __tablename__ = 'Genres'

    Id = mapped_column(Integer, primary_key=True)
    Name = mapped_column(String)
    Albums = relationship("Album",
                          secondary=album_genre_association_table,
                          back_populates="Genres")
    Playlists = relationship("Playlist",
                             secondary=playlist_genre_association_table,
                             back_populates="Genres")


class Album(Base):
    "A collection of tracks released by an artist"
    __tablename__ = 'Albums'

    Id = mapped_column(Integer, primary_key=True)
    Artist = mapped_column(String)
    Title = mapped_column(String)
    VolumeCount = mapped_column(Integer)
    MusicBrainzAlbumId = mapped_column(String)
    MusicBrainzAlbumArtistId = mapped_column(String)
    ReleaseYear = mapped_column(Integer)
    IsCompilation = mapped_column(Boolean)
    Tracks = relationship("Track")
    Genres = relationship("Genre",
                          secondary=album_genre_association_table,
                          back_populates="Albums")


class ArtistAlias(Base):
    "A list of alternative names by which an artist may be known"
    __tablename__ = 'ArtistAliases'

    Artist = mapped_column(String, primary_key=True)
    _AlternativeNames = mapped_column(String, default='[]')

    @property
    def AlternativeNames(self):
        return json.loads(self._AlternativeNames)

    @AlternativeNames.setter
    def AlternativeNames(self, value):
        self._AlternativeNames = json.dumps(value)


class Playlist(Base):
    "A custom collection of tracks"
    __tablename__ = 'Playlists'

    Id = mapped_column(Integer, primary_key=True)
    Title = mapped_column(String)
    Entries = relationship("PlaylistEntry",
                           order_by=PlaylistEntry.__table__.c.PlaylistIndex)
    Genres = relationship("Genre",
                          secondary=playlist_genre_association_table,
                          back_populates="Playlists")


class RadioStation(Base):
    "A streaming radio station"
    __tablename__ = 'RadioStations'

    Id = mapped_column(Integer, primary_key=True)
    Name = mapped_column(String)
    Url = mapped_column(String)
    ArtworkUrl = mapped_column(String)
    NowPlayingUrl = mapped_column(String)
    NowPlayingJq = mapped_column(String)
    NowPlayingArtworkUrl = mapped_column(String)
    NowPlayingArtworkJq = mapped_column(String)
    SortOrder = mapped_column(Integer)


class Track(Base):
    "A single track"
    __tablename__ = 'Tracks'

    Id = mapped_column(Integer, primary_key=True)
    Filepath = mapped_column(String, index=True)
    Title = mapped_column(String)
    Duration = mapped_column(Integer)
    Composer = mapped_column(String)
    Artist = mapped_column(String)
    Genre = mapped_column(Integer, ForeignKey("Genres.Id"))
    VolumeNumber = mapped_column(Integer)
    TrackCount = mapped_column(Integer)
    TrackNumber = mapped_column(Integer)
    ReleaseDate = mapped_column(DateTime)
    MusicBrainzTrackId = mapped_column(String)
    MusicBrainzArtistId = mapped_column(String)
    Album = mapped_column(Integer, ForeignKey("Albums.Id"))
    Artwork = mapped_column(Integer, ForeignKey("Artwork.Id"))
    ArtworkObject = relationship("Artwork", back_populates="Tracks")


class Artwork(Base):
    __tablename__ = 'Artwork'

    Id = mapped_column(Integer, primary_key=True)
    Path = mapped_column(String)  # either this or the next will be populated
    Blob = mapped_column(LargeBinary)
    BlobHash = mapped_column(String)
    Width = mapped_column(Integer)
    Height = mapped_column(Integer)
    Tracks = relationship("Track", back_populates="ArtworkObject", cascade="all, delete")


# Based on
# https://stackoverflow.com/questions/51419186/delete-parent-object-when-all-children-have-been-deleted-in-sqlalchemy
@event.listens_for(Track, 'before_delete')
def delete_unused_artwork(_mapper, _connection, track):
    @event.listens_for(Session, 'after_flush', once=True)
    def act_after_flush(session, _context):
        if track.ArtworkObject and not track.ArtworkObject.Tracks:
            session.delete(track.ArtworkObject)
