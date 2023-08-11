from enum import Enum


class WorkRequests(Enum):
    SCAN_DIRECTORY = 1
    DELETE_MISSING_TRACKS = 2
    DELETE_ALBUMS_WITHOUT_TRACKS = 3
    FETCH_FROM_YOUTUBE = 4
