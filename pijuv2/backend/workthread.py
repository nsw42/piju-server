import logging
import pathlib
from queue import Queue
import threading

from ..database.database import DatabaseAccess
from ..database.tidy import delete_missing_tracks, delete_albums_without_tracks
from ..scan.directory import scan_directory
from .workrequests import WorkRequests
from .ytdlp import fetch_audio


class WorkerThread(threading.Thread):
    def __init__(self, app, work_queue: Queue):
        super().__init__(name='WorkerThread', daemon=True)
        self.app = app
        self.work_queue = work_queue
        self.current_status = 'Not started'

    def run(self):
        print(f"WorkerThread: id={threading.get_native_id()} ident={threading.current_thread().ident}")
        while True:
            self.current_status = 'Idle'
            request = self.work_queue.get()

            with DatabaseAccess() as db:
                if request[0] == WorkRequests.SCAN_DIRECTORY:
                    dir_to_scan = pathlib.Path(request[1])
                    self.current_status = f'Scanning {dir_to_scan}'
                    scan_directory(dir_to_scan, db)

                elif request[0] == WorkRequests.DELETE_MISSING_TRACKS:
                    self.current_status = 'Deleting missing tracks'
                    delete_missing_tracks(db)

                elif request[0] == WorkRequests.DELETE_ALBUMS_WITHOUT_TRACKS:
                    self.current_status = 'Deleting albums without tracks'
                    delete_albums_without_tracks(db)

                elif request[0] == WorkRequests.FETCH_FROM_YOUTUBE:
                    url = request[1]
                    download_dir = request[2]
                    self.current_status = f'Fetching {url} to {download_dir}'
                    local_files = fetch_audio(url=url, download_dir=download_dir)
                    callback = request[3]
                    if callback:
                        callback(self.app, url, local_files)

                else:
                    logging.error(f"Unrecognised request: {request[0]}")
