import os
import subprocess

from .playerinterface import CurrentStatusStrings, PlayerInterface


class StreamPlayer(PlayerInterface):
    def __init__(self, audio_device: str):
        super().__init__()
        self.currently_playing = None
        self.player_subprocess = None
        self.audio_device = audio_device

    def play(self, name, url):
        if self.player_subprocess:
            self.stop()
        self.current_status = CurrentStatusStrings.PLAYING
        self.currently_playing = name
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

    def stop(self):
        if self.player_subprocess:
            self.player_subprocess.terminate()
        self.player_subprocess = None
        self.current_status = CurrentStatusStrings.STOPPED

    def set_volume(self, volume):
        self.current_volume = volume
