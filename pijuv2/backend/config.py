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

    def __init__(self, config_filepath):
        print(config_filepath)
        if config_filepath:
            self._init_from_file(config_filepath)
        else:
            self.music_dir = Path.home() / 'Music'

        if not self.music_dir or not self.music_dir.is_dir():
            raise ConfigException(f"Music directory {self.music_dir} not found")

    def _init_from_file(self, filepath):
        with filepath.open('r') as handle:
            data = json5.load(handle)
            self.music_dir = data.get('music_dir', None)
            if not self.music_dir:
                raise ConfigException(f"Config file {filepath} does not specify a value for music_dir")
            self.music_dir = Path(self.music_dir)
