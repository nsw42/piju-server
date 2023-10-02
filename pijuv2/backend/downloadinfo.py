from collections import namedtuple
from pathlib import Path
from typing import Union


DownloadInfo = namedtuple('DownloadInfo', 'filepath, artist, title, artwork, url, fake_trackid')
# filepath: Path
# artist: str
# title: str


class DownloadInfoDatabase:
    def __init__(self):
        self._id_to_download_info = {}
        self._filepath_to_id = {}
        self._next_id_to_allocate = -1

    def get_id_for_filepath(self, filepath: Union[str, Path]) -> int:
        if isinstance(filepath, Path):
            filepath = str(filepath)
        track_id = self._filepath_to_id.get(filepath)
        if track_id is None:
            track_id = self._next_id_to_allocate
            self._next_id_to_allocate -= 1
            self._filepath_to_id[filepath] = track_id
        return track_id

    def add_download_info(self, fakeid: int, download_info: DownloadInfo):
        self._id_to_download_info[fakeid] = download_info

    def get_download_info(self, fakeid: int) -> DownloadInfo:
        return self._id_to_download_info.get(fakeid)


class DownloadInfoDatabaseSingleton(DownloadInfoDatabase):
    __instance = None

    def __new__(cls):
        if DownloadInfoDatabaseSingleton.__instance is None:
            DownloadInfoDatabaseSingleton.__instance = DownloadInfoDatabase()
        return DownloadInfoDatabaseSingleton.__instance
