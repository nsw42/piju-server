from contextlib import nullcontext
import json
import os
from pathlib import Path
from queue import Queue
import socket

from flask import Flask, has_app_context
from flask_sock import ConnectionClosed

from ..database.database import Database
from ..player.fileplayer import FilePlayer
from ..player.streamplayer import StreamPlayer
from .config import Config
from .downloadhistory import DownloadHistory
from .nowplaying import get_current_status
from .routes import routes, sock
from .workthread import WorkerThread


def create_app(db_path: str, create_db=False) -> Flask:
    app = Flask(__name__)
    Database.init_db(app, db_path, create_db)
    config_file = Path(os.environ.get('PIJU_CONFIG', Config.default_filepath()))
    if not config_file.is_file():
        raise Exception(f"Config file {config_file} not found")
    app.piju_config = Config(config_file)
    app.work_queue = Queue()
    app.worker = WorkerThread(app, app.work_queue)
    app.config['SERVER_NAME'] = f'{socket.gethostname()}:5000'
    app.config['SECRET_KEY'] = 'piju-server-key'
    app.file_player = FilePlayer()
    app.stream_player = StreamPlayer()
    app.current_player = app.file_player
    app.api_version_string = '7.0'
    app.download_history = DownloadHistory()
    app.websocket_clients = []

    def state_change_callback():
        update_now_playing(app)
    app.file_player.set_state_change_callback(state_change_callback)
    app.stream_player.set_state_change_callback(state_change_callback)

    app.register_blueprint(routes)
    sock.init_app(app)

    return app


def update_now_playing(app):
    context_manager = nullcontext if has_app_context() else app.app_context
    with context_manager():
        data = json.dumps(get_current_status())
        for ws in list(app.websocket_clients):
            try:
                ws.send(data)
            except ConnectionClosed:
                app.websocket_clients.remove(ws)
