from contextlib import nullcontext
import json
import os
from pathlib import Path
from queue import Queue

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


class PijuApp(Flask):
    def __init__(self, db_path, create_db):
        super().__init__(__name__)
        Database.init_db(self, db_path, create_db)
        config_file = Path(os.environ.get('PIJU_CONFIG', Config.Defaults.FILEPATH))
        if not config_file.is_file():
            raise FileNotFoundError(f"Config file {config_file} not found")
        self.piju_config = Config(config_file)
        self.work_queue = Queue()
        self.worker = WorkerThread(self, self.work_queue)
        self.server_address = f'http://{self.piju_config.server_name}:5000'  # NB. *Not* config['SERVER_NAME']
        self.config['SECRET_KEY'] = 'piju-server-key'
        self.file_player = FilePlayer()
        self.stream_player = StreamPlayer()
        self.current_player = self.file_player
        self.api_version_string = '7.0'
        self.download_history = DownloadHistory()
        self.websocket_clients = []

        def state_change_callback():
            self.update_now_playing()
        self.file_player.set_state_change_callback(state_change_callback)
        self.stream_player.set_state_change_callback(state_change_callback)

        self.register_blueprint(routes)
        sock.init_app(self)

    def update_now_playing(self):
        context_manager = nullcontext if has_app_context() else self.app_context
        with context_manager():
            data = json.dumps(get_current_status())
            for ws in self.websocket_clients[:]:
                try:
                    ws.send(data)
                except ConnectionClosed:
                    self.websocket_clients.remove(ws)


def create_app(db_path: str, create_db=False) -> PijuApp:
    return PijuApp(db_path, create_db)
