from pathlib import Path
import socket
import json5


class ConfigException(Exception):
    """
    Exception thrown if there is a problem with the configuration file
    """


class Config:
    class Defaults:
        DOWNLOAD_DIR = Path('/tmp')
        FILEPATH = Path.home() / '.pijudrc'
        MUSIC_DIR = Path.home() / 'Music'
        SERVER_NAME = socket.gethostname()

    def __init__(self, config_filepath):
        if config_filepath:
            self._init_from_file(config_filepath)
        else:
            self.cookies_file = None
            self.music_dir = Config.Defaults.MUSIC_DIR
            self.download_dir = Config.Defaults.DOWNLOAD_DIR
            self.server_name = Config.Defaults.SERVER_NAME

        if self.cookies_file:
            if not self.cookies_file.is_file():
                raise ConfigException(f"Cookies file {self.cookies_file} not found")
            self.cookies_file = self.cookies_file.resolve()
        if not self.music_dir or not self.music_dir.is_dir():
            raise ConfigException(f"Music directory {self.music_dir} not found")
        if not self.download_dir.is_dir():
            raise ConfigException(f"Download directory {self.download_dir} not found")

    def _init_from_file(self, filepath):
        with filepath.open('r') as handle:
            data = json5.load(handle)
            self.cookies_file = Path(data.get('cookies', None))
            self.music_dir = Path(data.get('music_dir', Config.Defaults.MUSIC_DIR))
            self.download_dir = Path(data.get('download_dir', Config.Defaults.DOWNLOAD_DIR))
            self.server_name = data.get('server_name', Config.Defaults.SERVER_NAME)
