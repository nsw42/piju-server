"""
Player control functionality for the backend: an API-aware wrapper around ..player.*
"""

from http import HTTPStatus
from typing import Iterable

from flask import abort, current_app, url_for

from ..database.database import Database, DatabaseAccess, NotFoundException
from ..database.schema import Track
from .downloadinfo import DownloadInfo
from .workrequests import WorkRequests


def add_track_to_queue(track: Track):
    """
    Pre-requisite: the caller is responsible for ensuring that current_player
    is a queueing-capable player (ie the file_player)
    """
    has_artwork = (track.ArtworkPath or track.ArtworkBlob)
    artwork_uri = url_for('routes.get_artwork', trackid=track.Id) if has_artwork else None
    current_app.current_player.add_to_queue(track.Filepath, track.Id, track.Artist, track.Title, artwork_uri)


def play_downloaded_files(app, url, download_info: Iterable[DownloadInfo]):
    """
    A callback after an audio URL has been downloaded - executed within the
    context of WorkerThread, so cannot rely on accessing current_app
    """
    select_player(app, app.file_player)
    app.current_player.clear_queue()
    queue_downloaded_files(app, url, download_info)


def queue_downloaded_files(app, url, download_info: Iterable[DownloadInfo]):
    """
    A callback after an audio URL has been downloaded - executed within the
    context of WorkerThread, so cannot rely on accessing current_app
    """
    select_player(app, app.file_player)
    app.download_history.set_info(url, download_info)
    for one_download in download_info:
        app.current_player.add_to_queue(str(one_download.filepath),
                                        one_download.fake_trackid,
                                        one_download.artist, one_download.title,
                                        one_download.artwork)


def select_player(app, desired_player):
    if (app.current_player != desired_player) and (app.current_player is not None):
        app.current_player.stop()
    app.current_player = desired_player


def update_player_play_track_list(tracks: Iterable[Track], identifier: str, start_at_track_id: int):
    if start_at_track_id is None:
        play_from_index = 0
    else:
        track_ids = [track.Id for track in tracks]
        try:
            play_from_index = track_ids.index(start_at_track_id)
        except ValueError:
            abort(HTTPStatus.BAD_REQUEST, "Requested track is not in the specified album")
    select_player(current_app, current_app.file_player)
    current_app.current_player.set_queue(tracks, identifier)
    current_app.current_player.play_from_real_queue_index(play_from_index)


def update_player_play_album(db, albumid, trackid):
    try:
        album = db.get_album_by_id(albumid)
    except NotFoundException:
        abort(HTTPStatus.NOT_FOUND, description="Unknown album id")

    def track_sort_order(track):
        return (track.VolumeNumber if track.VolumeNumber else 0,
                track.TrackNumber if track.TrackNumber else 0)
    tracks = list(sorted(album.Tracks, key=track_sort_order))
    update_player_play_track_list(tracks, url_for('routes.get_album', albumid=albumid), trackid)


def update_player_play_from_local(db: Database, albumid: int, playlistid: int, queue_pos: int, trackid: int):
    select_player(current_app, current_app.file_player)

    if albumid is not None:
        update_player_play_album(db, albumid, trackid)

    elif playlistid is not None:
        update_player_play_playlist(db, playlistid, trackid)

    elif queue_pos is not None:
        update_player_play_from_queue(queue_pos, trackid)

    elif trackid:
        update_player_play_track(db, trackid)

    else:
        assert False, "Internal error: Unhandled code path"


def update_player_play_from_queue(queue_pos, trackid):
    # update_player_play has already ensured we're set up for file playback
    if not current_app.current_player.play_from_apparent_queue_index(queue_pos, trackid=trackid):
        abort(409, "Track index not found")


def update_player_play_from_radio(db: Database, stationid: int):
    stations = db.get_all_radio_stations()
    index = next((i for i, station in enumerate(stations) if station.Id == stationid), -1)
    if index == -1:
        abort(HTTPStatus.NOT_FOUND, "Requested station id not found")
    station = stations[index]
    select_player(current_app, current_app.stream_player)
    current_app.current_player.play(station.Name, station.Url, station.ArtworkUrl,
                                    index, len(stations),
                                    station.NowPlayingUrl, station.NowPlayingJq,
                                    station.NowPlayingArtworkUrl, station.NowPlayingArtworkJq)


def update_player_play_from_youtube(url):
    current_app.download_history.add(url)
    current_app.work_queue.put((WorkRequests.FETCH_FROM_YOUTUBE,
                                url,
                                current_app.piju_config.download_dir,
                                play_downloaded_files))


def update_player_streaming_prevnext(delta):
    current_url = current_app.current_player.currently_playing_url
    with DatabaseAccess() as db:
        stations = db.get_all_radio_stations()
        current_index = next((i for i, station in enumerate(stations) if station.Url == current_url), -1)
        if current_index > -1:
            new_index = current_index + delta
            if 0 <= new_index < len(stations):
                new_station = stations[new_index]
                current_app.current_player.play(new_station.Name, new_station.Url, new_station.ArtworkUrl,
                                                new_index, len(stations),
                                                new_station.NowPlayingUrl, new_station.NowPlayingJq,
                                                new_station.NowPlayingArtworkUrl, new_station.NowPlayingArtworkJq)


def update_player_play_playlist(db: Database, playlistid, trackid):
    try:
        playlist = db.get_playlist_by_id(playlistid)
    except NotFoundException:
        abort(HTTPStatus.NOT_FOUND, description="Unknown playlist id")
    update_player_play_track_list([entry.Track for entry in playlist.Entries],
                                  url_for('one_playlist', playlistid=playlistid),
                                  trackid)


def update_player_play_track(db: Database, trackid):
    # update_player_play has already ensured we're set up for file playback
    try:
        track = db.get_track_by_id(trackid)
    except NotFoundException:
        abort(HTTPStatus.NOT_FOUND, description="Unknown track id")
    current_app.current_player.clear_queue()
    add_track_to_queue(track)
