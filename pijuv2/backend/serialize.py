"""
Functions related to data serialization, ie converting from in-memory to
an over-the-wire representation
"""

import enum
from functools import lru_cache
import os.path
from typing import overload

from .routeconsts import RouteConstants
from ..database.database import Database
from ..database.schema import Album, Genre, Playlist, RadioStation, Track
from ..player.fileplayer import QueuedTrack


class InformationLevel(enum.Enum):
    NO_INFO = 0
    LINKS = 1
    ALL_INFO = 2
    DEBUG_INFO = 3  # All Info plus information that's not normally exposed via the API (eg file paths)

    @overload
    @staticmethod
    def from_string(info: str) -> 'InformationLevel':  # type: ignore
        ...

    @overload
    @staticmethod
    def from_string(info: str, default: 'InformationLevel') -> 'InformationLevel':
        ...


def information_level_from_string(info: str,
                                  default: InformationLevel = InformationLevel.LINKS) -> InformationLevel:
    info = info.lower()
    if info == 'none':
        return InformationLevel.NO_INFO
    elif info == 'links':
        return InformationLevel.LINKS
    elif info == 'all':
        return InformationLevel.ALL_INFO
    elif info == 'debug':
        return InformationLevel.DEBUG_INFO
    else:
        return default


InformationLevel.from_string = information_level_from_string


@lru_cache(maxsize=32)
def json_album(album: Album, include_tracks: InformationLevel):
    tracks = list(album.Tracks)
    tracks = sorted(tracks, key=lambda track: (track.VolumeNumber or 0, track.TrackNumber or 0))
    for track in tracks:
        if bool(track.Artwork):
            artwork_uri = RouteConstants.url_for_get_artwork(track.Artwork)
            break
    else:
        artwork_uri = None

    rtn = {
        'link': RouteConstants.url_for_get_album(album.Id),
        'artist': album.Artist,
        'title': album.Title,
        'releasedate': album.ReleaseYear,
        'iscompilation': album.IsCompilation,
        'numberdisks': album.VolumeCount,
        'artwork': {
            'link': artwork_uri,
        },
        'genres': [RouteConstants.url_for_get_genre(genre.Id) for genre in album.Genres],
    }
    if include_tracks == InformationLevel.LINKS:
        rtn['tracks'] = [RouteConstants.url_for_get_track(track.Id) for track in tracks]
    elif include_tracks in (InformationLevel.ALL_INFO, InformationLevel.DEBUG_INFO):
        include_debuginfo = (include_tracks == InformationLevel.DEBUG_INFO)
        rtn['tracks'] = [json_track(track, include_debuginfo=include_debuginfo) for track in tracks]
    return rtn


@lru_cache(maxsize=32)
def json_genre(genre: Genre, include_albums: InformationLevel, include_playlists: InformationLevel):
    rtn = {
        'link': RouteConstants.url_for_get_genre(genre.Id),
        'name': genre.Name,
    }
    if include_albums == InformationLevel.LINKS:
        rtn['albums'] = [RouteConstants.url_for_get_album(album.Id) for album in genre.Albums]
    elif include_albums in (InformationLevel.ALL_INFO, InformationLevel.DEBUG_INFO):
        rtn['albums'] = [json_album(album, include_tracks=include_albums) for album in genre.Albums]
    if include_playlists == InformationLevel.LINKS:
        rtn['playlists'] = [RouteConstants.url_for_get_one_playlist(playlist.Id) for playlist in genre.Playlists]
    elif include_playlists in (InformationLevel.ALL_INFO, InformationLevel.DEBUG_INFO):
        rtn['playlists'] = [json_playlist(playlist,
                                          include_genres=InformationLevel.NO_INFO,
                                          include_tracks=include_playlists)
                            for playlist in genre.Playlists]
    return rtn


@lru_cache(maxsize=32)
def json_playlist(playlist: Playlist, include_genres: InformationLevel, include_tracks: InformationLevel):
    entries = list(playlist.Entries)
    rtn = {
        'link': RouteConstants.url_for_get_one_playlist(playlist.Id),
        'title': playlist.Title,
    }
    if include_genres == InformationLevel.LINKS:
        rtn['genres'] = [RouteConstants.url_for_get_genre(genre.Id) for genre in playlist.Genres]
    elif include_genres in (InformationLevel.ALL_INFO, InformationLevel.DEBUG_INFO):
        rtn['genres'] = [json_genre(genre,
                                    include_albums=InformationLevel.NO_INFO,
                                    include_playlists=InformationLevel.NO_INFO) for genre in playlist.Genres]
    if include_tracks == InformationLevel.LINKS:
        rtn['tracks'] = [RouteConstants.url_for_get_track(entry.TrackId) for entry in entries]
    elif include_tracks in (InformationLevel.ALL_INFO, InformationLevel.DEBUG_INFO):
        include_debuginfo = (include_tracks == InformationLevel.DEBUG_INFO)
        rtn['tracks'] = [json_track(entry.Track, include_debuginfo=include_debuginfo) for entry in entries]
    return rtn


@lru_cache(maxsize=32)
def json_radio_station(station: RadioStation, include_urls: bool = False):
    rtn = {
        'link': RouteConstants.url_for_get_one_radio_station(station.Id),
        'name': station.Name,
        'artwork': station.ArtworkUrl
    }
    if include_urls:
        rtn['url'] = station.Url
        rtn['now_playing_url'] = station.NowPlayingUrl
        rtn['now_playing_jq'] = station.NowPlayingJq
        rtn['now_playing_artwork_url'] = station.NowPlayingArtworkUrl
        rtn['now_playing_artwork_jq'] = station.NowPlayingArtworkJq
    return rtn


@lru_cache(maxsize=32)
def json_track(track: Track, include_debuginfo: bool = False):
    if not track:
        return {}
    has_artwork = bool(track.Artwork)
    rtn = {
        'link': RouteConstants.url_for_get_track(track.Id),
        'artist': track.Artist,
        'title': track.Title,
        'genre': track.Genre,
        'disknumber': track.VolumeNumber,
        'tracknumber': track.TrackNumber,
        'trackcount': track.TrackCount,
        'fileformat': os.path.splitext(track.Filepath)[1],
        'album': RouteConstants.url_for_get_album(track.Album) if track.Album else '',
        'artwork': RouteConstants.url_for_get_artwork(track.Artwork) if has_artwork else None,
        'artworkinfo': RouteConstants.url_for_get_artwork_info(track.Artwork) if has_artwork else None,
    }
    if include_debuginfo:
        rtn['filepath'] = track.Filepath
    return rtn


@lru_cache(maxsize=32)
def json_track_or_file(db: Database,
                       queued_track: QueuedTrack,
                       include_debuginfo: bool = False):
    if queued_track.trackid >= 0:
        # A real track
        track = db.get_track_by_id(queued_track.trackid)
        return json_track(track, include_debuginfo)
    else:
        # A fake track
        rtn = {
            'link': RouteConstants.url_for_get_track(queued_track.trackid),
            'artist': queued_track.artist,
            'title': queued_track.title,
            'genre': None,
            'disknumber': None,
            'tracknumber': None,
            'trackcount': None,
            'fileformat': os.path.splitext(queued_track.filepath)[1],
            'album': None,
            'artwork': queued_track.artwork,
            'artworkinfo': None
        }
        if include_debuginfo:
            rtn['filepath'] = queued_track.filepath
        return rtn
