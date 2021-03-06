import logging
import pathlib
from queue import Queue
import threading

from ..database.database import DatabaseAccess
from ..scan.directory import scan_directory
from .workqueue import WorkRequests


class WorkerThread(threading.Thread):
    def __init__(self, work_queue: Queue):
        super().__init__(name='WorkerThread', daemon=True)
        self.work_queue = work_queue
        self.current_status = 'Not started'

    def run(self):
        print(f"WorkerThread: id={threading.get_native_id()} ident={threading.current_thread().ident}")
        while True:
            self.current_status = 'Idle'
            request = self.work_queue.get()

            with DatabaseAccess() as db:
                if request[0] == WorkRequests.ScanDirectory:
                    dir_to_scan = pathlib.Path(request[1])
                    self.current_status = 'Scanning %s' % dir_to_scan
                    scan_directory(dir_to_scan, db)

                else:
                    logging.error("Unrecognised request: %s" % request[0])
