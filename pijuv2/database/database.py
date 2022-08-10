import logging
from typing import Iterable, List

from sqlalchemy import create_engine, func, select, or_
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.pool import QueuePool

from .schema import Base, Album, Genre, Playlist, Track


FILENAME = 'file.db'


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
    def __init__(self, filename=None, path=None):
        if path:
            filename = str(path)
        elif filename is None:
            filename = FILENAME
        self.engine = create_engine('sqlite:///' + filename, poolclass=QueuePool)
        self.session = scoped_session(sessionmaker(bind=self.engine))

        # ensure tables exist
        Base.metadata.create_all(self.engine)

        self.session.commit()

    def commit(self):
        self.session.commit()

    def create_playlist(self, playlist: Playlist):
        self.session.add(playlist)
        self.session.commit()
        self.session.refresh(playlist)
        return playlist

    def update_playlist(self, playlistid: int, playlist: Playlist):
        existing_playlist = self.get_playlist_by_id(playlistid)
        if not existing_playlist:
            raise NotFoundException(f"Playlist {playlist.Id} does not exist")
        existing_playlist.Title = playlist.Title
        existing_playlist.Entries = playlist.Entries
        existing_playlist.Genres = playlist.Genres
        self.session.commit()
        return existing_playlist

    def delete_playlist(self, playlistid: int):
        playlist = self.get_playlist_by_id(playlistid)  # raises NotFoundException if necessary
        self.session.delete(playlist)
        self.session.commit()

    def ensure_album_exists(self, albumref: Album):
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
                self.session.add(trackref)
                self.session.commit()
                self.session.refresh(trackref)
                return trackref
            elif count == 1:
                return res.first()
            else:
                logging.fatal("Multiple results found for a track reference")
                assert False
        else:
            # we know we're updating a track
            track = self.get_track_by_id(trackref.Id)
            track.Filepath = trackref.Filepath
            track.Title = trackref.Title
            track.Duration = trackref.Duration
            track.Composer = trackref.Composer
            track.Artist = trackref.Artist
            track.Genre = trackref.Genre
            track.VolumeNumber = trackref.VolumeNumber
            track.TrackCount = trackref.TrackCount
            track.TrackNumber = trackref.TrackNumber
            track.ReleaseDate = trackref.ReleaseDate
            track.MusicBrainzTrackId = trackref.MusicBrainzTrackId
            track.MusicBrainzArtistId = trackref.MusicBrainzArtistId
            track.Album = trackref.Album
            track.ArtworkPath = trackref.ArtworkPath
            track.ArtworkBlob = trackref.ArtworkBlob
            track.ArtworkWidth = trackref.ArtworkWidth
            track.ArtworkHeight = trackref.ArtworkHeight
            return track

    def get_album_by_id(self, albumid: int) -> Album:
        """
        Return the Album object for a given id.
        Raises NotFoundException for an unknown id
        """
        res = self.session.query(Album).filter(
            Album.Id == albumid
        )
        try:
            return res.one()
        except Exception as e:
            raise convert_exception_class(e) from e

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
        result = self.session.execute(query)
        return result.scalars().all()

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

    def get_genre_by_id(self, genreid: int) -> Genre:
        """
        Return the Genre object for a given id.
        Raises NotFoundException for an unknown id
        """
        res = self.session.query(Genre).filter(
            Genre.Id == genreid
        )
        try:
            return res.one()
        except Exception as e:
            raise convert_exception_class(e) from e

    def get_playlist_by_id(self, playlistid: int) -> Playlist:
        """
        Return the Playlist object for a given id.
        Raises NotFoundException for an unknown id
        """
        res = self.session.query(Playlist).filter(
            Playlist.Id == playlistid
        )
        try:
            return res.one()
        except Exception as e:
            raise convert_exception_class(e) from e

    def get_track_by_id(self, trackid: int) -> Track:
        """
        Return the Track object for a given id.
        Raises NotFoundException for an unknown id
        """
        res = self.session.query(Track).filter(
            Track.Id == trackid
        )
        try:
            return res.one()
        except Exception as e:
            raise convert_exception_class(e) from e

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

    def get_nr_tracks(self):
        return self.session.query(Track).with_entities(func.count(Track.Id)).scalar()

    def search_for_albums(self, search_words: Iterable[str], limit=100) -> List[Album]:
        q = self.session.query(Album)
        for word in search_words:
            pattern = '%' + word + '%'
            q = q.filter(or_(Album.Title.ilike(pattern), Album.Artist.ilike(pattern)))
        q = q.order_by(Album.Artist).limit(limit)
        return q.all()

    def search_for_artist(self, search_words: Iterable[str], limit=100) -> List[Album]:
        """
        Return a list of Album objects where the artist
        matches the given name.
        If substring is True, then searches for
        """
        q = self.session.query(Album)
        for word in search_words:
            pattern = '%' + word + '%'
            q = q.filter(Album.Artist.ilike(pattern))
        q = q.order_by(Album.Artist).limit(limit)
        return q.all()

    def search_for_tracks(self, search_words: Iterable[str], query_limit=1000, return_limit=100) -> List[Track]:
        q = self.session.query(Track).join(Album)
        for word in search_words:
            pattern = '%' + word + '%'
            q = q.filter(or_(Track.Title.ilike(pattern), Album.Title.ilike(pattern), Track.Artist.ilike(pattern)))
        q = q.limit(query_limit)
        tracks = q.all()
        # sort tracks by quality of match
        lower_case_words = [word.lower() for word in search_words]

        def score_track(track):
            # print(track.Title)
            # print('=======================')
            score = 0
            for word in lower_case_words:
                if (word in track.Title.lower()):
                    # print(word, 3)
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
    def __init__(self):
        self.db = Database()

    def __enter__(self):
        return self.db

    def __exit__(self, type, value, traceback):
        self.db.commit()
        del self.db
