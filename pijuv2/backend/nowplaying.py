from flask import current_app

from ..database.database import DatabaseAccess
from ..player.playerinterface import CurrentStatusStrings
from .serialize import json_track_or_file


def get_current_status():
    with DatabaseAccess() as db:
        c_p = current_app.current_player
        rtn = {
            'WorkerStatus': current_app.worker.current_status,
            'PlayerStatus': c_p.current_status,
            'PlayerVolume': c_p.current_volume,
            'NumberAlbums': db.get_nr_albums(),
            'NumberArtworks': db.get_nr_artworks(),
            'NumberTracks': db.get_nr_tracks(),
            'CurrentTrackIndex': None if (c_p.current_track_index is None) else (c_p.current_track_index + 1),
            'MaximumTrackIndex': c_p.number_of_tracks,
            'ApiVersion': current_app.api_version_string,
        }
        if c_p == current_app.file_player:
            rtn['CurrentTracklistUri'] = c_p.current_tracklist_identifier
            if c_p.current_track:
                rtn['CurrentTrack'] = json_track_or_file(db, c_p.current_track)
                rtn['CurrentArtwork'] = rtn['CurrentTrack']['artwork']
            else:
                rtn['CurrentTrack'] = {}
                rtn['CurrentArtwork'] = None
        elif c_p == current_app.stream_player:
            rtn['CurrentStream'] = c_p.currently_playing_name
            rtn['CurrentArtwork'] = c_p.currently_playing_artwork
            if c_p.current_status == CurrentStatusStrings.PLAYING and c_p.now_playing_artist and c_p.now_playing_track:
                rtn['CurrentTrack'] = {
                    'artist': c_p.now_playing_artist,
                    'title': c_p.now_playing_track
                }
    return rtn
