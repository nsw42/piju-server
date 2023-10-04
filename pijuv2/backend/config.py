from pathlib import Path
import json5


class ConfigException(Exception):
    """
    Exception thrown if there is a problem with the configuration file
    """


class Config:
    @staticmethod
    def default_filepath():
        return Path.home() / '.pijudrc'

    @staticmethod
    def default_musicdir():
        return Path.home() / 'Music'

    def __init__(self, config_filepath):
        if config_filepath:
            self._init_from_file(config_filepath)
        else:
            self.audio_device = None  # Use system default
            self.music_dir = Path.home() / 'Music'
            self.download_dir = Path('/tmp')

        if not self.music_dir or not self.music_dir.is_dir():
            raise ConfigException(f"Music directory {self.music_dir} not found")
        if not self.download_dir.is_dir():
            raise ConfigException(f"Download directory {self.download_dir} not found")

    def _init_from_file(self, filepath):
        with filepath.open('r') as handle:
            data = json5.load(handle)
            self.audio_device = data.get('audio_device', None)
            self.music_dir = data.get('music_dir')
            self.music_dir = Path(self.music_dir) if self.music_dir else Config.default_musicdir()

            default_download_dir = '/tmp'
            self.download_dir = data.get('download_dir', default_download_dir)
            self.download_dir = Path(self.download_dir)
