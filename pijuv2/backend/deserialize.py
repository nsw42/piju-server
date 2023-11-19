"""
Functions related to data deserialization, ie converting from an
over-the-wire representation to an in-memory object
"""

from typing import List, Tuple

from flask import current_app, request
from werkzeug.exceptions import BadRequest, NotFound

from ..database.database import Database, NotFoundException
from ..database.schema import Playlist, PlaylistEntry, RadioStation


def build_playlist_from_api_data(db: Database) -> Tuple[Playlist, List[str]]:
    data = request.get_json()
    if not data:
        raise BadRequest('No data found in request')
    title = data.get('title')
    trackids = extract_ids(data.get('tracks', []))
    files = data.get('files', [])
    if title in (None, ""):
        raise BadRequest("Playlist title must be specified")
    if (not trackids) and (not files):
        raise BadRequest("Either a list of tracks or a list of files must be specified")
    if (trackids) and (files):
        raise BadRequest("Only one of a list of tracks and a list of files is permitted")
    if files:
        tracks = []
        missing = []
        for filepath in files:
            fullpath = current_app.piju_config.music_dir / filepath
            track = db.get_track_by_filepath(str(fullpath))
            if track:
                tracks.append(track)
            else:
                print(f"Could not find a track at {filepath} - looked in {fullpath}")
                missing.append(filepath)
    else:
        missing = []
        if None in trackids:
            raise BadRequest("Invalid track reference")
        try:
            tracks = [db.get_track_by_id(trackid) for trackid in trackids]
        except NotFoundException as exc:
            raise NotFound("Unknown track id") from exc
    if not tracks:
        raise BadRequest("No tracks found. Will not create an empty playlist.")
    playlist_entries = []
    for index, track in enumerate(tracks):
        playlist_entries.append(PlaylistEntry(PlaylistIndex=index, TrackId=track.Id))
    genres = set(track.Genre for track in tracks if track.Genre is not None)
    genres = list(genres)
    genres = [db.get_genre_by_id(genre) for genre in genres]
    return Playlist(Title=title, Entries=playlist_entries, Genres=genres), missing


def build_radio_station_from_api_data() -> RadioStation:
    data = request.get_json()
    if data is None:
        raise BadRequest('No data found in request')
    station_name = data.get('name')
    if not station_name:
        raise BadRequest('Missing station name')
    url = data.get('url')
    if not url:
        raise BadRequest('Missing station URL')
    artwork_url = data.get('artwork')  # optional
    now_playing_url = data.get('now_playing_url')  # optional
    now_playing_jq = data.get('now_playing_jq')  # optional
    now_playing_artwork_url = data.get('now_playing_artwork_url')  # optional
    now_playing_artwork_jq = data.get('now_playing_artwork_jq')  # optional
    return RadioStation(Name=station_name, Url=url, ArtworkUrl=artwork_url,
                        NowPlayingUrl=now_playing_url, NowPlayingJq=now_playing_jq,
                        NowPlayingArtworkUrl=now_playing_artwork_url, NowPlayingArtworkJq=now_playing_artwork_jq)


def extract_id(uri_or_id):
    if uri_or_id and isinstance(uri_or_id, str) and '/' in uri_or_id:
        # this is a uri, map it to a string representation of an id, then fall-through
        uri_or_id = uri_or_id.rsplit('/', 1)[1]
    if uri_or_id and isinstance(uri_or_id, str) and uri_or_id.isdigit():
        uri_or_id = int(uri_or_id)
    return uri_or_id if isinstance(uri_or_id, int) else None


def extract_ids(uris_or_ids):
    return [extract_id(uri_or_id) for uri_or_id in uris_or_ids]


def parse_bool(bool_str: str):
    if bool_str.lower() in ('y', 'yes', 'true'):
        return True
    return False
