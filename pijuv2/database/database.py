import logging
from typing import Any, Iterable, List

from sqlalchemy import create_engine, func, select, or_
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.pool import QueuePool

from .schema import Base, Album, Genre, Playlist, RadioStation, Track


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


class Database():
    DEFAULT_FILENAME = 'file.db'

    def __init__(self, path=None, create=False):
        if path:
            filename = str(path)
        else:
            filename = Database.DEFAULT_FILENAME
        self.engine = create_engine('sqlite:///' + filename, poolclass=QueuePool)
        self.session = scoped_session(sessionmaker(bind=self.engine))
        if create:
            Base.metadata.create_all(self.engine)
            self.session.commit()

    def commit(self):
        self.session.commit()

    def add_radio_station(self, station: RadioStation):
        self.session.add(station)
        self.session.commit()
        self.session.refresh(station)
        return station

    def get_all_radio_stations(self) -> List[RadioStation]:
        result = self.session.execute(select(RadioStation).order_by(RadioStation.SortOrder))
        return result.scalars().all()

    def create_playlist(self, playlist: Playlist):
        self.session.add(playlist)
        self.session.commit()
        self.session.refresh(playlist)
        return playlist

    def update_playlist(self, playlistid: int, playlist: Playlist):
        existing_playlist = self.get_playlist_by_id(playlistid)
        if not existing_playlist:
            raise NotFoundException(f"Playlist {playlistid} does not exist")
        existing_playlist.Title = playlist.Title
        existing_playlist.Entries = playlist.Entries
        existing_playlist.Genres = playlist.Genres
        self.session.commit()
        return existing_playlist

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
        self.session.commit()
        return existing_station

    def delete_album(self, albumid: int):
        album = self.get_album_by_id(albumid)  # raises NotFoundException if necessary
        self.session.delete(album)
        self.session.commit()

    def delete_playlist(self, playlistid: int):
        playlist = self.get_playlist_by_id(playlistid)  # raises NotFoundException if necessary
        self.session.delete(playlist)
        self.session.commit()

    def delete_radio_station(self, stationid: int):
        station = self.get_radio_station_by_id(stationid)  # raises NotFoundException if necessary
        self.session.delete(station)
        self.session.commit()

    def delete_track(self, trackid: int):
        track = self.get_track_by_id(trackid)  # raises NotFoundException if necessary
        self.session.delete(track)
        self.session.commit()

    def ensure_album_exists(self, albumref: Album) -> Album:
        """
        Ensure the given album reference is present in the database,
        and return a fully populated object.
        """
        if albumref.IsCompilation:
            albumref.Artist = None
        res = self.session.query(Album).filter(
            Album.Title == albumref.Title,
            Album.Artist == albumref.Artist
        )
        # TODO: use res.one_or_none() ??
        count = res.count()
        if count == 0:
            # Album does not exist
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
            logging.fatal(f"Multiple results found for album reference: {albumref.Artist}: {albumref.Title}")
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
        if trackref.Id is None:
            # creating track
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
                logging.debug("New track: %s", trackref.Filepath)
                self.session.add(trackref)
                self.session.commit()
                self.session.refresh(trackref)
                return trackref

            if count > 1:
                logging.fatal("Multiple results found for a track reference")
                assert False

            logging.debug(f"ensure_track_exists: track already existed: {trackref.Filepath}")
            track = res.first()
        else:
            # we know we're updating a track
            track = self.get_track_by_id(trackref.Id)

        # We now know we've found a track in the database
        # Update it if necessary - except for cross-references (eg Album)

        for attr in ['Filepath', 'Title', 'Duration', 'Composer', 'Artist', 'Genre',
                     'VolumeNumber', 'TrackCount', 'TrackNumber', 'ReleaseDate',
                     'MusicBrainzTrackId', 'MusicBrainzArtistId',
                     'ArtworkPath', 'ArtworkBlob', 'ArtworkWidth', 'ArtworkHeight']:
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

    def get_albums_without_tracks(self) -> List[Album]:
        """
        Return a list of Album objects where each album has no
        """
        return self.session.query(Album).filter(~Album.Tracks.any()).all()

    def get_all_albums(self) -> List[Album]:
        """
        Primarily for debugging
        """
        result = self.session.execute(select(Album).order_by(Album.Artist, Album.Title))
        return result.scalars().all()

    def get_all_genres(self) -> List[Genre]:
        """
        Primarily for debugging
        """
        result = self.session.execute(select(Genre).order_by(Genre.Name))
        return result.scalars().all()

    def get_all_playlists(self) -> List[Playlist]:
        """
        Primarily for debugging
        """
        result = self.session.execute(select(Playlist).order_by(Playlist.Title))
        return result.scalars().all()

    def get_all_tracks(self, limit=None) -> List[Track]:
        """
        Primarily for debugging
        """
        query = self.session.query(Track).order_by(Track.Artist, Track.Album, Track.TrackNumber)
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_artist(self, search_string: str, substring: bool, limit=100) -> List[Album]:
        """
        Return a list of Album objects where the artist
        matches the given name.
        If substring is True, then searches for
        """
        if substring:
            search_string = '%' + search_string + '%'
        return (self.session.query(Album)
                .filter(Album.Artist.ilike(search_string))
                .order_by(Album.Artist)
                .limit(limit)
                .all())

    def get_x_by_id(self, x_type: Any, x_id: int) -> Any:
        """
        Return the X object for a given id, where X is indicated by x_type (Genre, Playlist, Track, etc)
        Raises NotFoundException for an unknown id
        """
        res = self.session.query(x_type).filter(
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

    def get_track_by_filepath(self, path: str) -> Track:
        """
        Return the Track object for a given file path,
        or None if there is no match in the database.
        """
        res = self.session.query(Track).filter(
            func.lower(Track.Filepath) == func.lower(path)
        )
        return res.one_or_none()

    def get_nr_albums(self):
        return self.session.query(Album).with_entities(func.count(Album.Id)).scalar()

    def get_nr_genres(self):
        return self.session.query(Genre).with_entities(func.count(Genre.Id)).scalar()

    def get_nr_tracks(self):
        return self.session.query(Track).with_entities(func.count(Track.Id)).scalar()

    def search_for_albums(self, search_words: Iterable[str], limit=100) -> List[Album]:
        query = self.session.query(Album)
        for word in search_words:
            pattern = '%' + word + '%'
            query = query.filter(or_(Album.Title.ilike(pattern), Album.Artist.ilike(pattern)))
        query = query.order_by(Album.Artist).limit(limit)
        return query.all()

    def search_for_artist(self, search_words: Iterable[str], limit=100) -> List[Album]:
        """
        Return a list of Album objects where the artist
        matches the given name.
        If substring is True, then searches for
        """
        query = self.session.query(Album)
        for word in search_words:
            pattern = '%' + word + '%'
            query = query.filter(Album.Artist.ilike(pattern))
        query = query.order_by(Album.Artist).limit(limit)
        return query.all()

    def search_for_tracks(self, search_words: Iterable[str], query_limit=1000, return_limit=100) -> List[Track]:
        query = self.session.query(Track).join(Album)
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
            # print(track.Title)
            # print('=======================')
            score = 0
            track_lower = track.Title.lower()
            track_title_words = track_lower.split()
            for word in lower_case_words:
                if (word in track_lower):
                    # print(word, 3)
                    # Prioritise exact word matches over substring matches
                    if word in track_title_words:
                        score += 4
                    else:
                        score += 3
                elif (word not in track.Artist.lower()):
                    # assert word in get_album_by_id(track.Album).Title.lower()
                    # print(word, 2)
                    score += 2
                else:
                    # print(word, 1)
                    score += 1
            return score
        tracks = [(score_track(track), track) for track in tracks]
        tracks.sort(key=lambda s_t: s_t[0], reverse=True)  # best matches (== biggest score) at the top
        return [track for (score, track) in tracks][:return_limit]


class DatabaseAccess:
    def __init__(self, path=None, create=False):
        self.db = Database(path=path, create=create)

    def __enter__(self):
        return self.db

    def __exit__(self, typ, value, traceback):
        self.db.commit()
        del self.db
