from enum import Enum


class WorkRequests(Enum):
    ScanDirectory = 1
    DeleteMissingTracks = 2
    DeleteAlbumsWithoutTracks = 3
    FetchFromYouTube = 4
