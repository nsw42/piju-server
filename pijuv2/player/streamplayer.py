import os
import subprocess

from .playerinterface import CurrentStatusStrings, PlayerInterface


class StreamPlayer(PlayerInterface):
    def __init__(self, audio_device: str):
        super().__init__()
        self.currently_playing_name = None
        self.currently_playing_url = None
        self.currently_playing_artwork = None
        self.player_subprocess = None
        self.audio_device = audio_device

    def _stop(self):
        """
        Stop playback, but don't clear metadata, supporting both stop() and pause()
        """
        if self.player_subprocess:
            self.player_subprocess.terminate()
        self.player_subprocess = None

    def play(self, name: str, url: str, artwork: str, current_index: int, nr_stations: int):
        if self.player_subprocess:
            self.stop()
        self.current_status = CurrentStatusStrings.PLAYING
        self.currently_playing_name = name
        self.currently_playing_url = url
        self.currently_playing_artwork = artwork
        self.current_track_index = current_index
        self.number_of_tracks = nr_stations
        if self.audio_device:
            child_environment = dict(os.environ)
            child_environment['SDL_AUDIODRIVER'] = 'alsa'
            child_environment['AUDIODEV'] = self.audio_device
        else:
            child_environment = None
        # -nodisp: disable graphical display
        # -vn: disable video
        # -sn: disable subtitles
        cmd = ['ffplay', '-nodisp', '-vn', '-sn',
               '-volume', str(self.current_volume),
               '-loglevel', 'warning',
               url]
        self.player_subprocess = subprocess.Popen(cmd, env=child_environment)

    def pause(self):
        """
        Required for interface compatibility but we cannot actually
        pause. So just stop, but make it look like we've paused.
        """
        self._stop()
        self.current_status = CurrentStatusStrings.PAUSED

    def resume(self):
        """
        Like pause(), required for interface compatibility.
        Restarts playing the last url that was played.
        """
        if self.currently_playing_name:
            self.play(self.currently_playing_name,
                      self.currently_playing_url,
                      self.currently_playing_artwork,
                      self.current_track_index,
                      self.number_of_tracks)

    def stop(self):
        self._stop()
        self.current_status = CurrentStatusStrings.STOPPED
        self.currently_playing_name = self.currently_playing_url = self.currently_playing_artwork = None

    def set_volume(self, volume):
        self.current_volume = volume
