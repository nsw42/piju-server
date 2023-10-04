"""
Functions related to data serialization, ie converting from in-memory to
an over-the-wire representation
"""

import os.path

from flask import url_for

from ..database.schema import Album, Genre, Playlist, RadioStation, Track


class InformationLevel:
    NoInfo = 0
    Links = 1
    AllInfo = 2
    DebugInfo = 3  # All Info plus information that's not normally exposed via the API (eg file paths)

    @staticmethod
    def from_string(info: str, default: 'InformationLevel' = Links):
        info = info.lower()
        if info == 'none':
            return InformationLevel.NoInfo
        elif info == 'links':
            return InformationLevel.Links
        elif info == 'all':
            return InformationLevel.AllInfo
        elif info == 'debug':
            return InformationLevel.DebugInfo
        else:
            return default


def json_album(album: Album, include_tracks: InformationLevel):
    tracks = list(album.Tracks)
    tracks = sorted(tracks, key=lambda track: (track.VolumeNumber or 0, track.TrackNumber or 0))
    for track in tracks:
        if track.ArtworkPath or track.ArtworkBlob:
            artwork_uri = url_for('get_artwork', trackid=track.Id)
            artwork_width = track.ArtworkWidth
            artwork_height = track.ArtworkHeight
            break
    else:
        artwork_uri = artwork_width = artwork_height = None

    rtn = {
        'link': url_for('get_album', albumid=album.Id),
        'artist': album.Artist,
        'title': album.Title,
        'releasedate': album.ReleaseYear,
        'iscompilation': album.IsCompilation,
        'numberdisks': album.VolumeCount,
        'artwork': {
            'link': artwork_uri,
            'width': artwork_width,
            'height': artwork_height
        },
        'genres': [url_for('get_genre', genreid=genre.Id) for genre in album.Genres],
    }
    if include_tracks == InformationLevel.Links:
        rtn['tracks'] = [url_for('get_track', trackid=track.Id) for track in tracks]
    elif include_tracks in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        include_debuginfo = (include_tracks == InformationLevel.DebugInfo)
        rtn['tracks'] = [json_track(track, include_debuginfo=include_debuginfo) for track in tracks]
    return rtn


def json_genre(genre: Genre, include_albums: InformationLevel, include_playlists: InformationLevel):
    rtn = {
        'link': url_for('get_genre', genreid=genre.Id),
        'name': genre.Name,
    }
    if include_albums == InformationLevel.Links:
        rtn['albums'] = [url_for('get_album', albumid=album.Id) for album in genre.Albums]
    elif include_albums in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        rtn['albums'] = [json_album(album, include_tracks=include_albums) for album in genre.Albums]
    if include_playlists == InformationLevel.Links:
        rtn['playlists'] = [url_for('one_playlist', playlistid=playlist.Id) for playlist in genre.Playlists]
    elif include_playlists in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        rtn['playlists'] = [json_playlist(playlist,
                                          include_genres=InformationLevel.NoInfo,
                                          include_tracks=include_playlists)
                            for playlist in genre.Playlists]
    return rtn


def json_playlist(playlist: Playlist, include_genres: InformationLevel, include_tracks: InformationLevel):
    entries = list(playlist.Entries)
    rtn = {
        'link': url_for('one_playlist', playlistid=playlist.Id),
        'title': playlist.Title,
    }
    if include_genres == InformationLevel.Links:
        rtn['genres'] = [url_for('get_genre', genreid=genre.Id) for genre in playlist.Genres]
    elif include_genres in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        rtn['genres'] = [json_genre(genre,
                                    include_albums=InformationLevel.NoInfo,
                                    include_playlists=InformationLevel.NoInfo) for genre in playlist.Genres]
    if include_tracks == InformationLevel.Links:
        rtn['tracks'] = [url_for('get_track', trackid=entry.TrackId) for entry in entries]
    elif include_tracks in (InformationLevel.AllInfo, InformationLevel.DebugInfo):
        include_debuginfo = (include_tracks == InformationLevel.DebugInfo)
        rtn['tracks'] = [json_track(entry.Track, include_debuginfo=include_debuginfo) for entry in entries]
    return rtn


def json_radio_station(station: RadioStation, include_urls: bool = False):
    rtn = {
        'link': url_for('one_radio_station', stationid=station.Id),
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


def json_track(track: Track, include_debuginfo: bool = False):
    if not track:
        return {}
    has_artwork = track.ArtworkPath or track.ArtworkBlob
    rtn = {
        'link': url_for('get_track', trackid=track.Id),
        'artist': track.Artist,
        'title': track.Title,
        'genre': track.Genre,
        'disknumber': track.VolumeNumber,
        'tracknumber': track.TrackNumber,
        'trackcount': track.TrackCount,
        'fileformat': os.path.splitext(track.Filepath)[1],
        'album': url_for('get_album', albumid=track.Album) if track.Album else '',
        'artwork': url_for('get_artwork', trackid=track.Id) if has_artwork else None,
        'artworkinfo': url_for('get_artwork_info', trackid=track.Id) if has_artwork else None,
    }
    if include_debuginfo:
        rtn['filepath'] = track.Filepath
    return rtn


def json_track_or_file(db, queued_track, include_debuginfo: bool = False):
    if queued_track.trackid >= 0:
        # A real track
        track = db.get_track_by_id(queued_track.trackid)
        return json_track(track, include_debuginfo)
    else:
        # A fake track
        rtn = {
            'link': url_for('get_track', trackid=queued_track.trackid),
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
