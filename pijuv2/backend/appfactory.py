import os
from pathlib import Path
from queue import Queue

from flask import Flask

from ..player.fileplayer import FilePlayer
from ..player.streamplayer import StreamPlayer
from .config import Config
from .downloadhistory import DownloadHistory
from .routes import routes
from .workthread import WorkerThread


def create_app() -> Flask:
    app = Flask(__name__)
    config_file = Path(os.environ.get('PIJU_CONFIG', Config.default_filepath()))
    if not config_file.is_file():
        raise Exception(f"Config file {config_file} not found")
    app.piju_config = Config(config_file)
    app.work_queue = Queue()
    app.worker = WorkerThread(app.work_queue)
    app.file_player = FilePlayer(mp3audiodevice=app.piju_config.audio_device)
    app.stream_player = StreamPlayer(audio_device=app.piju_config.audio_device)
    app.current_player = app.file_player
    app.api_version_string = '6.0'
    app.download_history = DownloadHistory()
    app.register_blueprint(routes)
    return app
