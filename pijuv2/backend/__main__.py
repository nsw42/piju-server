from queue import Queue
import json

from flask import Flask

from ..database.database import Database
from .workqueue import WorkRequests
from .workthread import WorkerThread

app = Flask(__name__)
music_dir = '/Users/Shared/iTunes Media/Music'


@app.route("/")
def current_status():
    rtn = {
        'WorkerStatus': app.worker.current_status
    }
    return json.dumps(rtn)


if __name__ == '__main__':
    db = Database()  # pre-create tables
    queue = Queue()
    queue.put((WorkRequests.ScanDirectory, music_dir))
    app.worker = WorkerThread(queue)
    app.worker.start()
    app.run(debug=True, use_reloader=False)
