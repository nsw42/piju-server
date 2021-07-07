import logging
import pathlib
from queue import Queue
import threading

from ..database.database import Database
from ..scan.directory import scan_directory
from .workqueue import WorkRequests


class WorkerThread(threading.Thread):
    def __init__(self, work_queue: Queue):
        super().__init__(name='WorkerThread', daemon=True)
        self.work_queue = work_queue
        self.current_status = 'Not started'

    def run(self):
        print("WorkerThread: %s" % threading.get_native_id())
        while True:
            self.current_status = 'Idle'
            request = self.work_queue.get()

            db = Database()

            if request[0] == WorkRequests.ScanDirectory:
                dir_to_scan = pathlib.Path(request[1])
                self.current_status = 'Scanning %s' % dir_to_scan
                scan_directory(dir_to_scan, db)

            else:
                logging.error("Unrecognised request: %s" % request[0])

            del db
