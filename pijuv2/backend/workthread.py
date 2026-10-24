import logging
import pathlib
from queue import Queue
import threading

from ..database.database import DatabaseAccess
from ..database.tidy import (delete_albums_without_tracks,
                             delete_artwork_without_tracks,
                             delete_empty_genres,
                             delete_missing_tracks)
from ..scan.directory import scan_directory
from .serialize import clear_cached_responses
from .workrequests import WorkRequests
from .ytdlp import fetch_audio

# Requests that may change albums, genres, playlists or tracks, and hence make cached responses stale
LIBRARY_CHANGING_REQUESTS = (
    WorkRequests.SCAN_DIRECTORY,
    WorkRequests.DELETE_MISSING_TRACKS,
    WorkRequests.DELETE_ALBUMS_WITHOUT_TRACKS,
    WorkRequests.DELETE_EMPTY_GENRES,
    WorkRequests.DELETE_ARTWORK_WITHOUT_TRACKS,
)


class WorkerThread(threading.Thread):
    def __init__(self, app, work_queue: Queue):
        super().__init__(name='WorkerThread', daemon=True)
        self.app = app
        self.work_queue = work_queue
        self.current_status = 'Not started'

    def run(self):
        print(f"WorkerThread: id={threading.get_native_id()} ident={threading.current_thread().ident}")
        while True:
            self.set_current_status('Idle')
            request = self.work_queue.get()
            self.process_request(request)

    def process_request(self, request):
        with self.app.app_context():
            with DatabaseAccess() as db:
                match request[0]:
                    case WorkRequests.SCAN_DIRECTORY:
                        dir_to_scan = pathlib.Path(request[1])
                        self.set_current_status(f'Scanning {dir_to_scan}')
                        scan_directory(dir_to_scan, db)

                    case WorkRequests.DELETE_MISSING_TRACKS:
                        self.set_current_status('Deleting missing tracks')
                        delete_missing_tracks(db)

                    case WorkRequests.DELETE_ALBUMS_WITHOUT_TRACKS:
                        self.set_current_status('Deleting albums without tracks')
                        delete_albums_without_tracks(db)

                    case WorkRequests.DELETE_ARTWORK_WITHOUT_TRACKS:
                        self.set_current_status('Deleting artwork without tracks')
                        delete_artwork_without_tracks(db)

                    case WorkRequests.FETCH_FROM_YOUTUBE:
                        url = request[1]
                        download_info = self.app.download_history.get_info(url)
                        if (not download_info) or (not all(dl.filepath.is_file() for dl in download_info)):
                            download_dir = request[2]
                            self.set_current_status(f'Fetching {url} to {download_dir}')
                            download_info = fetch_audio(url=url, download_dir=download_dir)
                            self.app.download_history.set_info(url, download_info)
                        callback = request[3]
                        if callback:
                            callback(self.app, download_info)

                    case WorkRequests.DELETE_EMPTY_GENRES:
                        self.set_current_status('Deleting genres without albums/playlists')
                        delete_empty_genres(db)

                    case _:
                        logging.error(f"Unrecognised request: {request[0]}")

            # Only clear the caches once the changes have been committed, otherwise a concurrent
            # request could re-populate them from the database before the commit
            if request[0] in LIBRARY_CHANGING_REQUESTS:
                clear_cached_responses()

    def set_current_status(self, status: str):
        self.current_status = status
        self.app.send_now_playing_update()
