from contextlib import nullcontext
import os
from pathlib import Path
from queue import Queue

from flask import Flask, has_app_context
from flask_socketio import SocketIO

from ..database.database import Database
from ..player.fileplayer import FilePlayer
from ..player.streamplayer import StreamPlayer
from .config import Config
from .downloadhistory import DownloadHistory
from .nowplayingws import on_ws_connect, broadcast_now_playing_update
from .routes import routes
from .workthread import WorkerThread


def create_app(db_path: str, create_db=False) -> Flask:
    app = Flask(__name__)
    config_file = Path(os.environ.get('PIJU_CONFIG', Config.default_filepath()))
    if not config_file.is_file():
        raise Exception(f"Config file {config_file} not found")
    app.piju_config = Config(config_file)
    app.work_queue = Queue()
    app.worker = WorkerThread(app, app.work_queue)
    app.socketio = SocketIO(app, cors_allowed_origins='*')
    app.socketio.on_event('connect', on_ws_connect)
    app.api_version_string = '6.1'
    app.download_history = DownloadHistory()
    app.register_blueprint(routes)
    app.config['SERVER_NAME'] = '192.168.0.102:5000'
    app.config['SECRET_KEY'] = 'piju-server-key'
    Database.init_db(app, db_path, create_db)
    app.file_player = FilePlayer(app.socketio.start_background_task)
    app.stream_player = StreamPlayer(app.socketio.start_background_task)
    app.current_player = app.file_player

    def update_now_playing():
        print('>update_now_playing')
        context_manager = nullcontext if has_app_context() else app.app_context
        with context_manager():
            print('  app context established')
            broadcast_now_playing_update(app.socketio)
            print('  message broadcast')

    app.file_player.set_state_change_callback(update_now_playing)
    app.stream_player.set_state_change_callback(update_now_playing)

    return app
