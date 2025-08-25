from typing import cast

from ..database.database import DatabaseAccess
from ..player.playerinterface import CurrentStatusStrings
from ..player.streamplayer import StreamPlayer
from .appwrapper import current_piju_app
from .serialize import json_track_or_file


def get_current_status():
    with DatabaseAccess() as db:
        c_p = current_piju_app.current_player
        rtn = {
            'WorkerStatus': current_piju_app.worker.current_status,
            'PlayerStatus': c_p.current_status,
            'PlayerVolume': c_p.current_volume,
            'NumberAlbums': db.get_nr_albums(),
            'NumberArtworks': db.get_nr_artworks(),
            'NumberTracks': db.get_nr_tracks(),
            'CurrentTrackIndex': None if (c_p.current_track_index is None) else (c_p.current_track_index + 1),
            'MaximumTrackIndex': c_p.number_of_tracks,
            'ApiVersion': current_piju_app.api_version_string,
        }
        if c_p == current_piju_app.file_player:
            rtn['CurrentTracklistUri'] = c_p.current_tracklist_identifier
            if c_p.current_track:
                rtn['CurrentTrack'] = json_track_or_file(db, c_p.current_track)
                rtn['CurrentArtwork'] = rtn['CurrentTrack']['artwork']
            else:
                rtn['CurrentTrack'] = {}
                rtn['CurrentArtwork'] = None
        elif c_p == current_piju_app.stream_player:
            stream_player = cast(StreamPlayer, c_p)
            rtn['CurrentStream'] = stream_player.currently_playing_name
            rtn['CurrentArtwork'] = stream_player.currently_playing_artwork
            if c_p.current_status == CurrentStatusStrings.PLAYING \
                and stream_player.now_playing_artist \
                    and stream_player.now_playing_track:
                rtn['CurrentTrack'] = {
                    'artist': stream_player.now_playing_artist,
                    'title': stream_player.now_playing_track
                }
    return rtn
