import hashlib
import logging
import sqlite3
import unicodedata
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, TYPE_CHECKING

from flask_sqlalchemy import SQLAlchemy

from sqlalchemy import distinct, event, func, select, or_
from sqlalchemy.engine import Engine
from sqlalchemy.sql.expression import true
from sqlalchemy.exc import NoResultFound, MultipleResultsFound

from .displaygenre import DEFAULT_DISPLAY_GENRE_NAME, DisplayGenreIcon, DisplayGenreViewStyle, normalize_genre_name
from .schema import Base, Album, ArtistAlias, Artwork, DisplayGenre, DisplayGenreMapping, Genre, Playlist
from .schema import RadioStation, Track
from .schema import album_genre_association_table, playlist_genre_association_table

if not TYPE_CHECKING:
    func: Callable  # fixes false positives from pylint

SORT_IGNORED_CHARACTERS = '"\'\u2018\u2019\u201c\u201d'
SORT_KEY_SQL_FUNCTION = 'piju_sort_key'
# Compilations are stored with no artist, but are displayed (and so should be sorted) as this
COMPILATION_SORT_ARTIST = 'Various Artists'


def sort_key_for_string(value: Optional[str]) -> Optional[str]:
    """
    The sort key for a string: case-insensitive, accent-insensitive, and ignoring quote marks.

    >>> sort_key_for_string('"Weird Al" Yankovic')
    'weird al yankovic'
    >>> sort_key_for_string('\u00d3lafur Arnalds')
    'olafur arnalds'
    """
    if value is None:
        return None
    for ch in SORT_IGNORED_CHARACTERS:
        value = value.replace(ch, '')
    decomposed = unicodedata.normalize('NFKD', value)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


@event.listens_for(Engine, "connect")
def _register_sort_key_function(dbapi_connection, _connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        dbapi_connection.create_function(SORT_KEY_SQL_FUNCTION, 1, sort_key_for_string, deterministic=True)


def sort_key(column):
    """
    A sort key for a text column that is case- and accent-insensitive and ignores quote marks,
    so that, for example, '"Weird Al" Yankovic' sorts under W and 'Ólafur Arnalds' sorts under O
    """
    return getattr(func, SORT_KEY_SQL_FUNCTION)(column)


class PijuDatabaseException(Exception):
    """
    Base class for all database exceptions
    """


class NotFoundException(PijuDatabaseException):
    """
    The requested item could not be found
    """


class DatabaseIntegrityException(PijuDatabaseException):
    """
    Something is amiss with the database.
    Typically caused by finding multiple results when
    at most one was expected.
    """


class UnknownException(PijuDatabaseException):
    """
    Something bad happened, but it's not clear what
    """


def convert_exception_class(exc):
    if isinstance(exc, NoResultFound):
        return NotFoundException
    elif isinstance(exc, MultipleResultsFound):
        return DatabaseIntegrityException
    else:
        return UnknownException


def calcaulate_blobhash(artwork: Artwork) -> str:
    hasher = hashlib.sha1(artwork.Blob, usedforsecurity=False)
    return hasher.hexdigest()


class Database():
    SQLITE_PREFIX = 'sqlite:///'
    DEFAULT_URI = SQLITE_PREFIX + 'file.db'

    db = SQLAlchemy(model_class=Base)
    initialised = False

    @staticmethod
    def init_db(app, path=None, create=False):
        if path:
            uri = Database.SQLITE_PREFIX + str(path)
        else:
            uri = Database.DEFAULT_URI
        app.config['SQLALCHEMY_DATABASE_URI'] = uri
        Database.db.init_app(app)
        if create:
            with app.app_context():
                Database.db.create_all()
        Database.initialised = True

    def __init__(self):
        assert Database.initialised

    def commit(self):
        Database.db.session.commit()

    def _get_artist_alias_object(self, artist: str) -> ArtistAlias | None:
        res = Database.db.session.query(ArtistAlias).filter(ArtistAlias.Artist == artist)
        try:
            return res.one()
        except NoResultFound:
            return None

    def add_artist_alias(self, artist: str, also_known_as: str):
        # NB Caller is responsible for adding the reverse alias
        alias_obj = self._get_artist_alias_object(artist)
        if alias_obj:
            # We're adding to an existing list
            alias_obj.AlternativeNames = alias_obj.AlternativeNames + [also_known_as]
        else:
            alias_obj = ArtistAlias(Artist=artist, AlternativeNames=[also_known_as])
            Database.db.session.add(alias_obj)
        Database.db.session.commit()

    def get_artist_aliases(self, artist: str) -> List[str]:
        alias_obj = self._get_artist_alias_object(artist)
        return list(alias_obj.AlternativeNames) if alias_obj else []

    def delete_artist_aliases(self, artist: str) -> List[str]:
        # Returns the list of alternative names that had been set for the artist
        alias_obj = self._get_artist_alias_object(artist)
        if not alias_obj:
            raise NotFoundException()
        alternatives = list(alias_obj.AlternativeNames)
        Database.db.session.delete(alias_obj)
        Database.db.session.commit()
        return alternatives

    def remove_one_artist_alias(self, artist: str, also_known_as: str):
        alias_obj = self._get_artist_alias_object(artist)
        if not alias_obj:
            raise NotFoundException()
        alternatives = list(alias_obj.AlternativeNames)
        try:
            # Note that alias_obj.AlternativeNames is a transient value, so must be assigned to
            alternatives.remove(also_known_as)
        except ValueError as exc:
            raise NotFoundException() from exc
        alias_obj.AlternativeNames = alternatives
        Database.db.session.commit()

    def add_radio_station(self, station: RadioStation):
        Database.db.session.add(station)
        Database.db.session.commit()
        Database.db.session.refresh(station)
        return station

    def get_all_radio_stations(self) -> Sequence[RadioStation]:
        result = Database.db.session.execute(select(RadioStation).order_by(RadioStation.SortOrder))
        return result.scalars().all()

    def create_playlist(self, playlist: Playlist):
        Database.db.session.add(playlist)
        Database.db.session.commit()
        Database.db.session.refresh(playlist)
        return playlist

    def update_playlist(self, playlistid: int, playlist: Playlist):
        existing_playlist = self.get_playlist_by_id(playlistid)
        if not existing_playlist:
            raise NotFoundException(f"Playlist {playlistid} does not exist")
        existing_playlist.Title = playlist.Title
        existing_playlist.Entries = playlist.Entries
        existing_playlist.Genres = playlist.Genres
        Database.db.session.commit()
        return existing_playlist

    def set_genre_display_genre(self, genreid: int, display_genre_id: int) -> Genre:
        """
        Move a genre to a different display genre, and remember the choice
        for any genre of the same name that is created in future.
        Raises NotFoundException if either id is unknown.
        """
        genre = self.get_genre_by_id(genreid)
        display_genre = self.get_display_genre_by_id(display_genre_id)
        genre.DisplayGenreId = display_genre.Id
        mapping_name = normalize_genre_name(genre.Name)
        mapping = Database.db.session.get(DisplayGenreMapping, mapping_name)
        if mapping:
            mapping.DisplayGenreId = display_genre.Id
        else:
            Database.db.session.add(DisplayGenreMapping(GenreName=mapping_name, DisplayGenreId=display_genre.Id))
        Database.db.session.commit()
        return genre

    def update_radio_station(self, stationid: int, station: RadioStation):
        existing_station = self.get_radio_station_by_id(stationid)
        if not existing_station:
            raise NotFoundException(f"Radio {stationid} does not exist")
        existing_station.Name = station.Name
        existing_station.Url = station.Url
        existing_station.ArtworkUrl = station.ArtworkUrl
        existing_station.NowPlayingUrl = station.NowPlayingUrl
        existing_station.NowPlayingJq = station.NowPlayingJq
        existing_station.NowPlayingArtworkUrl = station.NowPlayingArtworkUrl
        existing_station.NowPlayingArtworkJq = station.NowPlayingArtworkJq
        existing_station.SortOrder = station.SortOrder
        Database.db.session.commit()
        return existing_station

    def delete_album(self, albumid: int):
        album = self.get_album_by_id(albumid)  # raises NotFoundException if necessary
        Database.db.session.delete(album)
        Database.db.session.commit()

    def delete_artwork(self, artworkid: int):
        artwork = self.get_artwork_by_id(artworkid)  # raises NotFoundException if necessary
        Database.db.session.delete(artwork)
        Database.db.session.commit()

    def delete_genre(self, genreid: int):
        genre = self.get_genre_by_id(genreid)  # raises NotFoundException if necessary
        Database.db.session.delete(genre)
        Database.db.session.commit()

    def delete_playlist(self, playlistid: int):
        playlist = self.get_playlist_by_id(playlistid)  # raises NotFoundException if necessary
        Database.db.session.delete(playlist)
        Database.db.session.commit()

    def delete_radio_station(self, stationid: int):
        station = self.get_radio_station_by_id(stationid)  # raises NotFoundException if necessary
        Database.db.session.delete(station)
        Database.db.session.commit()

    def delete_track(self, trackid: int):
        track = self.get_track_by_id(trackid)  # raises NotFoundException if necessary
        Database.db.session.delete(track)
        Database.db.session.commit()

    def ensure_album_exists(self, albumref: Album) -> Album:
        """
        Ensure the given album reference is present in the database,
        and return a fully populated object.
        """
        if albumref.IsCompilation:
            albumref.Artist = None
        album = Database.db.session.query(Album).filter(
            Album.Title == albumref.Title,
            Album.Artist == albumref.Artist
        ).one_or_none()
        if album is None:
            # Album does not exist
            Database.db.session.add(albumref)
            Database.db.session.commit()
            Database.db.session.refresh(albumref)
            return albumref
        else:
            commit = False
            if (album.VolumeCount is None) or (albumref.VolumeCount is not None
                                               and album.VolumeCount < albumref.VolumeCount):
                album.VolumeCount = albumref.VolumeCount
                commit = True
            if (album.ReleaseYear is None) or (albumref.ReleaseYear is not None
                                               and album.ReleaseYear < albumref.ReleaseYear):
                album.ReleaseYear = albumref.ReleaseYear
                commit = True
            if commit:
                Database.db.session.commit()
            return album

    def ensure_artwork_exists(self, artworkref: Artwork) -> Artwork:
        """
        Ensure the given artwork reference is present in the database,
        and return a fully populated object.
        Required properties of the artwork reference are one of Path or Blob,
        plus Width and Height.
        The returned object will additionally have Id set.
        """
        if artworkref.Path:
            existing_artwork = Database.db.session.query(Artwork).filter(
                Artwork.Path == artworkref.Path
            ).one_or_none()
        elif artworkref.Blob:
            artworkref.BlobHash = calcaulate_blobhash(artworkref)
            possible_existing_artworks = Database.db.session.query(Artwork).filter(
                Artwork.BlobHash == artworkref.BlobHash
            ).all()
            for possible_existing_artwork in possible_existing_artworks:
                if possible_existing_artwork.Blob == artworkref.Blob:
                    existing_artwork = possible_existing_artwork
                    break
            else:
                existing_artwork = None
        else:
            assert False
        if existing_artwork:
            logging.debug(f"ensure_artwork_exists: existing artwork: {existing_artwork.Id}: "
                          f"{existing_artwork.Path} / {len(existing_artwork.Blob or '')} bytes "
                          f"({existing_artwork.Width} x {existing_artwork.Height})")
            # Has the artwork size changed?
            if ((existing_artwork.Width != artworkref.Width) or (existing_artwork.Height != artworkref.Height)):
                existing_artwork.Width = artworkref.Width
                existing_artwork.Height = artworkref.Height
                Database.db.session.commit()
                Database.db.session.refresh(existing_artwork)
            return existing_artwork
        else:
            Database.db.session.add(artworkref)
            Database.db.session.commit()
            Database.db.session.refresh(artworkref)
            logging.debug(f"ensure_artwork_exists: no existing artwork: New id {artworkref.Id}")
            return artworkref

    def ensure_default_display_genre_exists(self) -> DisplayGenre:
        """
        Return the display genre that is home to genres with no explicit mapping,
        creating it if necessary.
        """
        display_genre = Database.db.session.query(DisplayGenre).filter(
            DisplayGenre.IsDefault == true()
        ).first()
        if display_genre is None:
            max_sort_order = Database.db.session.query(func.max(DisplayGenre.SortOrder)).scalar()
            display_genre = DisplayGenre(Name=DEFAULT_DISPLAY_GENRE_NAME,
                                         Icon=DisplayGenreIcon.MUSIC.value,
                                         ViewStyle=DisplayGenreViewStyle.LIST_OF_ALBUMS.value,
                                         SortOrder=0 if max_sort_order is None else max_sort_order + 1,
                                         IsDefault=True)
            Database.db.session.add(display_genre)
            Database.db.session.commit()
            Database.db.session.refresh(display_genre)
        return display_genre

    def get_display_genre_for_genre_name(self, genre_name: str) -> DisplayGenre:
        """
        Return the display genre that a genre of the given name belongs to:
        the one it has been explicitly mapped to, or the default display genre.
        """
        display_genre = Database.db.session.query(DisplayGenre).join(DisplayGenreMapping).filter(
            DisplayGenreMapping.GenreName == normalize_genre_name(genre_name)
        ).one_or_none()
        return display_genre or self.ensure_default_display_genre_exists()

    def ensure_genre_exists(self, genre_name: str) -> Genre:
        """
        Ensure the given genre exists
        """
        genre = Database.db.session.query(Genre).filter(
            Genre.Name == genre_name
        ).one_or_none()
        if genre is None:
            genre = Genre(Name=genre_name, DisplayGenreId=self.get_display_genre_for_genre_name(genre_name).Id)
            Database.db.session.add(genre)
            Database.db.session.commit()
            Database.db.session.refresh(genre)
        return genre

    def ensure_track_exists(self, trackref: Track) -> Track:
        """
        Return the Id for the given Track reference
        Also looks up trackref.Genre in the database if it's a string, and replaces it with a fk to the genre table
        """
        if isinstance(trackref.Genre, str):
            trackref.Genre = self.ensure_genre_exists(trackref.Genre).Id
        if trackref.Id is None:
            # creating track
            res = Database.db.session.query(Track).filter(
                Track.Album == trackref.Album,
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
                logging.debug("New track: %s", trackref.Filepath)
                Database.db.session.add(trackref)
                Database.db.session.commit()
                Database.db.session.refresh(trackref)
                return trackref

            if count > 1:
                logging.fatal("Multiple results found for a track reference")
                assert False

            logging.debug(f"ensure_track_exists: track already existed: {trackref.Filepath}")
            track = res.first()
            assert track
        else:
            # we know we're updating a track
            track = self.get_track_by_id(trackref.Id)

        # We now know we've found a track in the database
        # Update it if necessary - except for cross-references (eg Album)

        for attr in ['Filepath', 'Title', 'Duration', 'Composer', 'Artist', 'Genre',
                     'VolumeNumber', 'TrackCount', 'TrackNumber', 'ReleaseDate',
                     'MusicBrainzTrackId', 'MusicBrainzArtistId', 'Album', 'Artwork']:
            old_val = getattr(track, attr)
            new_val = getattr(trackref, attr)
            if old_val != new_val:
                logging.debug("ensure_track_exists: %s changing %s from %s to %s",
                              trackref.Filepath, attr, old_val, new_val)
                setattr(track, attr, new_val)

        return track

    def get_album_by_id(self, albumid: int) -> Album:
        """
        Return the Album object for a given id.
        Raises NotFoundException for an unknown id
        """
        return self.get_x_by_id(Album, albumid)

    def get_artwork_by_id(self, artworkid: int) -> Artwork:
        """
        Return the Artwork object for a given id.
        Raises NotFoundException for an unknown id
        """
        return self.get_x_by_id(Artwork, artworkid)

    def get_albums_without_tracks(self) -> Sequence[Album]:
        """
        Return a list of Album objects where the album contains no Tracks
        """
        return Database.db.session.query(Album).filter(~Album.Tracks.any()).all()

    def get_all_albums(self) -> Sequence[Album]:
        """
        Primarily for debugging
        """
        result = Database.db.session.execute(select(Album).order_by(Album.Artist, Album.Title))
        return result.scalars().all()

    def get_all_artworks(self) -> Sequence[Artwork]:
        """
        Primarily for debugging
        """
        result = Database.db.session.execute(select(Artwork).order_by(Artwork.Id))
        return result.scalars().all()

    def get_all_display_genres(self) -> Sequence[DisplayGenre]:
        result = Database.db.session.execute(select(DisplayGenre).order_by(DisplayGenre.SortOrder, DisplayGenre.Id))
        return result.scalars().all()

    def get_all_genres(self) -> Sequence[Genre]:
        """
        Primarily for debugging
        """
        result = Database.db.session.execute(select(Genre).order_by(Genre.Name))
        return result.scalars().all()

    def get_all_playlists(self) -> Sequence[Playlist]:
        """
        Primarily for debugging
        """
        result = Database.db.session.execute(select(Playlist).order_by(Playlist.Title))
        return result.scalars().all()

    def get_all_tracks(self, limit=None) -> Sequence[Track]:
        """
        Primarily for debugging
        """
        query = Database.db.session.query(Track).order_by(Track.Artist, Track.Album, Track.TrackNumber)
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_all_tracks_paged(self, start_id, limit) -> Optional[Sequence[Track]]:
        """
        Calling get_all_tracks() can exceed available memory.
        get_all_tracks_paged() therefore allows stepping through all tracks in bite-size chunks.
        Returns None if start_id is greater than the maximum allocated track id;
        otherwise, returns a (possibly-empty) list of Track items.
        Can therefore be used as:
            ```
            start = 0
            page_size = 100
            while (tracks := db.get_all_tracks_paged(start, page_size)) is not None:
                # do something with tracks
                start += page_size
            ```
        """
        query = select(Track).where(start_id <= Track.Id).where(Track.Id < start_id + limit).order_by(Track.Id)
        result = Database.db.session.execute(query).scalars().all()
        if not result:
            # No tracks found - was start_id too big, or is there just a big gap in the allocated ids?
            max_track_id = Database.db.session.query(Track).with_entities(func.max(Track.Id)).first()
            logging.debug("max_track: %s", max_track_id)
            if (max_track_id is None) or (start_id > max_track_id[0]):
                return None
            return []
        return result

    def get_artist(self, search_string: str, substring: bool, limit=100) -> Sequence[Album]:
        """
        Return a list of Album objects where the artist
        matches the given name.
        If substring is True, then searches for the given
        search_string anywhere in the Album artist name;
        if substring is False, then the search string must
        match (case-insensitive) the complete artist name;
        """
        if substring:
            search_string = '%' + search_string + '%'
        return (Database.db.session.query(Album)
                .filter(Album.Artist.ilike(search_string))
                .order_by(Album.Artist)
                .limit(limit)
                .all())

    def get_artwork_without_tracks(self) -> Sequence[Artwork]:
        """
        Return a list of Artwork objects where the artwork is not referenced by
        any tracks
        """
        return Database.db.session.query(Artwork).filter(~Artwork.Tracks.any()).all()

    def get_compilations(self, limit=100) -> Sequence[Album]:
        """
        Return a list of Album objects where the IsCompilation flag is set to True
        """
        result = Database.db.session.execute(
            select(Album)
            .where(Album.IsCompilation == true())
            .order_by(Album.Title)
            .limit(limit)
        )
        return result.scalars().all()

    def get_display_genre_by_id(self, display_genre_id: int) -> DisplayGenre:
        """
        Return the DisplayGenre object for a given id.
        Raises NotFoundException for an unknown id
        """
        return self.get_x_by_id(DisplayGenre, display_genre_id)

    def get_display_genre_album_counts(self) -> Dict[int, int]:
        """
        Return a dict mapping display genre id to the number of albums in any of its genres.
        Display genres that contain no albums are omitted.
        """
        result = Database.db.session.execute(
            select(Genre.DisplayGenreId, func.count(distinct(album_genre_association_table.c.album_id)))
            .join(album_genre_association_table, Genre.Id == album_genre_association_table.c.genre_id)
            .where(Genre.DisplayGenreId.is_not(None))
            .group_by(Genre.DisplayGenreId)
        )
        return {display_genre_id: count for display_genre_id, count in result}

    def get_display_genre_albums(self, display_genre_id: int, offset: int, limit: int) -> Tuple[Sequence[Album], int]:
        """
        Return one page of the albums in any of the genres of the given display genre,
        together with the total number of such albums.
        Albums are ordered by artist, then release year, then title, with compilations sorted as 'Various Artists'.
        """
        album_ids = (select(album_genre_association_table.c.album_id)
                     .join(Genre, Genre.Id == album_genre_association_table.c.genre_id)
                     .where(Genre.DisplayGenreId == display_genre_id))
        in_display_genre = Album.Id.in_(album_ids)
        total = Database.db.session.execute(select(func.count(Album.Id)).where(in_display_genre)).scalar()
        result = Database.db.session.execute(
            select(Album)
            .where(in_display_genre)
            # Album.Id as the final key keeps the order, and hence the pages, stable
            .order_by(sort_key(func.coalesce(Album.Artist, COMPILATION_SORT_ARTIST)), Album.ReleaseYear,
                      sort_key(Album.Title), Album.Id)
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all(), total

    def get_display_genre_playlists(self, display_genre_id: int) -> Sequence[Playlist]:
        """
        Return the playlists in any of the genres of the given display genre
        """
        playlist_ids = (select(playlist_genre_association_table.c.playlist_id)
                        .join(Genre, Genre.Id == playlist_genre_association_table.c.genre_id)
                        .where(Genre.DisplayGenreId == display_genre_id))
        result = Database.db.session.execute(
            select(Playlist).where(Playlist.Id.in_(playlist_ids)).order_by(Playlist.Title, Playlist.Id)
        )
        return result.scalars().all()

    def get_empty_genres(self) -> Sequence[Genre]:
        """
        Return a list of Genre objects that contain neither albums nor playlists
        """
        return Database.db.session.query(Genre).filter(~Genre.Albums.any()).filter(~Genre.Playlists.any()).all()

    def get_x_by_id(self, x_type: Any, x_id: int) -> Any:
        """
        Return the X object for a given id, where X is indicated by x_type (Genre, Playlist, Track, etc)
        Raises NotFoundException for an unknown id
        """
        res = Database.db.session.query(x_type).filter(
            x_type.Id == x_id
        )
        try:
            return res.one()
        except Exception as exc:
            raise convert_exception_class(exc) from exc

    def get_genre_by_id(self, genreid: int) -> Genre:
        """
        Return the Genre object for a given id.
        Raises NotFoundException for an unknown id
        """
        return self.get_x_by_id(Genre, genreid)

    def get_playlist_by_id(self, playlistid: int) -> Playlist:
        """
        Return the Playlist object for a given id.
        Raises NotFoundException for an unknown id
        """
        return self.get_x_by_id(Playlist, playlistid)

    def get_radio_station_by_id(self, stationid: int) -> RadioStation:
        return self.get_x_by_id(RadioStation, stationid)

    def get_track_by_id(self, trackid: int) -> Track:
        """
        Return the Track object for a given id.
        Raises NotFoundException for an unknown id
        """
        return self.get_x_by_id(Track, trackid)

    def get_track_by_filepath(self, path: str) -> Track | None:
        """
        Return the Track object for a given file path,
        or None if there is no match in the database.
        """
        res = Database.db.session.query(Track).filter(
            func.lower(Track.Filepath) == func.lower(path)
        )
        return res.one_or_none()

    def get_nr_albums(self):
        return Database.db.session.query(Album).with_entities(func.count(Album.Id)).scalar()

    def get_nr_artworks(self):
        return Database.db.session.query(Artwork).with_entities(func.count(Artwork.Id)).scalar()

    def get_nr_genres(self):
        return Database.db.session.query(Genre).with_entities(func.count(Genre.Id)).scalar()

    def get_nr_tracks(self):
        return Database.db.session.query(Track).with_entities(func.count(Track.Id)).scalar()

    def search_for_albums(self, search_words: Iterable[str], limit=100) -> List[Album]:
        """
        Return a list of Album objects where the album title
        or the artist name matches the given search words.
        """
        query = Database.db.session.query(Album)
        for word in search_words:
            pattern = '%' + word + '%'
            query = query.filter(or_(Album.Title.ilike(pattern), Album.Artist.ilike(pattern)))
        query = query.order_by(Album.Artist, Album.ReleaseYear).limit(limit)
        return query.all()

    def search_for_artist(self, search_words: Iterable[str], limit=100) -> List[Album]:
        """
        Return a list of Album objects where the artist
        matches the given search words.
        """
        query = Database.db.session.query(Album)
        for word in search_words:
            pattern = '%' + word + '%'
            query = query.filter(Album.Artist.ilike(pattern))
        query = query.order_by(Album.Artist).limit(limit)
        return query.all()

    def search_for_tracks(self, search_words: Iterable[str], query_limit=1000, return_limit=100) -> List[Track]:
        """
        Return a list of Track objects where the track title, album title or artist name
        matches the given search words.
        """
        query = Database.db.session.query(Track).join(Album)
        for word in search_words:
            pattern = '%' + word + '%'
            query = query.filter(or_(Track.Title.ilike(pattern),
                                     Album.Title.ilike(pattern),
                                     Track.Artist.ilike(pattern)))
        query = query.limit(query_limit)
        tracks = query.all()
        # sort tracks by quality of match
        lower_case_words = [word.lower() for word in search_words]

        def score_track(track):
            score = 0
            track_lower = track.Title.lower()
            track_title_words = track_lower.split()
            for word in lower_case_words:
                if (word in track_lower):
                    # Prioritise exact word matches over substring matches
                    if word in track_title_words:
                        score += 4
                    else:
                        score += 3
                elif (word not in track.Artist.lower()):
                    score += 2
                else:
                    score += 1
            return score
        scored_tracks = [(score_track(track), track) for track in tracks]
        scored_tracks.sort(key=lambda s_t: s_t[0], reverse=True)  # best matches (== biggest score) at the top
        return [track for (_, track) in scored_tracks][:return_limit]


class DatabaseAccess:
    def __init__(self):
        self.db = Database()

    def __enter__(self):
        return self.db

    def __exit__(self, typ, value, traceback):
        self.db.commit()
        del self.db
