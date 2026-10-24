from contextlib import nullcontext
import json
import os
from pathlib import Path
from queue import Queue
import subprocess

from flask import Flask, has_app_context
from flask_sock import ConnectionClosed

from ..database.database import Database
from ..player.fileplayer import FilePlayer
from ..player.streamplayer import StreamPlayer
from .config import Config
from .downloadhistory import DownloadHistory
from .nowplaying import get_current_status
from .routes import routes, sock, queue_data_for_websocket_client
from .workthread import WorkerThread


class PijuApp(Flask):
    def __init__(self, config_file: Path | None, db_path: Path, create_db: bool):
        super().__init__(__name__)
        Database.init_db(self, db_path, create_db)
        if config_file is None:
            config_file = Path(os.environ.get('PIJU_CONFIG', Config.Defaults.FILEPATH))
        if not config_file.is_file():
            raise FileNotFoundError(f"Config file {config_file} not found")
        self.version = get_server_version()
        self.piju_config = Config(config_file)
        self.work_queue = Queue()
        self.worker = WorkerThread(self, self.work_queue)
        self.server_address = f'http://{self.piju_config.server_name}:5000'  # NB. *Not* config['SERVER_NAME']
        self.file_player = FilePlayer()
        self.stream_player = StreamPlayer()
        self.current_player = self.file_player
        self.api_version_string = '9.3'
        self.download_history = DownloadHistory()
        self.status_websocket_clients = []
        self.queue_websocket_clients = []

        def state_change_callback():
            self.send_now_playing_update()
        self.file_player.set_state_change_callback(state_change_callback)
        self.stream_player.set_state_change_callback(state_change_callback)

        self.register_blueprint(routes)
        sock.init_app(self)

    def send_now_playing_update(self):
        context_manager = nullcontext if has_app_context() else self.app_context
        with context_manager():
            data = json.dumps(get_current_status())
            for ws in self.status_websocket_clients[:]:
                try:
                    ws.send(data)
                except ConnectionClosed:
                    self.status_websocket_clients.remove(ws)
        # if the current track has changed, that could result in the queue
        # updating too (e.g. we've moved to the next item in the queue) so
        # send an update to that, too
        if self.current_player.has_queue:
            self.send_queue_update()

    def send_queue_update(self):
        context_manager = nullcontext if has_app_context() else self.app_context
        with context_manager():
            for client in self.queue_websocket_clients[:]:
                try:
                    client.ws.send(json.dumps(queue_data_for_websocket_client(client)))
                except ConnectionClosed:
                    self.queue_websocket_clients.remove(client)


def get_server_version() -> str:
    for path in Path(__file__).parents:
        git = path / '.git'
        if git.is_dir():
            child = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, check=True)
            return child.stdout.strip()
    return 'unknown'


def create_app(config_file: Path | None, db_path: Path, create_db: bool = False) -> PijuApp:
    return PijuApp(config_file, db_path, create_db)
