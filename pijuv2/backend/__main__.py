from argparse import ArgumentParser
import doctest
import logging
import mimetypes
from pathlib import Path
from queue import Queue

from flask import Flask

from ..database.database import Database
from ..player.fileplayer import FilePlayer
from ..player.streamplayer import StreamPlayer
from .config import Config
from .downloadhistory import DownloadHistory
from .routes import routes
from .workthread import WorkerThread


app = Flask(__name__)

mimetypes.init()


# HELPER FUNCTIONS ----------------------------------------------------------------------------

def parse_args():
    parser = ArgumentParser()
    parser.add_argument('-a', '--mp3audiodevice', action='store',
                        help='Set audio device for mpg123')
    parser.add_argument('-c', '--config', metavar='FILE', type=Path,
                        help=f"Load configuration from FILE. Default is {str(Config.default_filepath())}")
    parser.add_argument('-d', '--database', metavar='FILE', type=Path,
                        help="Set database path to FILE. Default is %(default)s")
    parser.add_argument('-t', '--doctest', action='store_true',
                        help="Run self-test and exit")
    parser.set_defaults(doctest=False,
                        config=None,
                        database='file.db')
    args = parser.parse_args()
    if args.config and not args.config.is_file():
        parser.error(f"Specified configuration file ({str(args.config)}) could not be found")
    if (args.config is None) and (Config.default_filepath().is_file()):
        args.config = Config.default_filepath()
    if not args.database.is_file():
        parser.error("Specified database file does not exist. Use `run.sh` (or alembic) to initialise the database")
    return args


# RESPONSE HEADERS --------------------------------------------------------------------------------

@app.after_request
def add_security_headers(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp


# MAIN --------------------------------------------------------------------------------------------

def main():
    args = parse_args()

    if args.doctest:
        doctest.testmod()
    else:
        logging.basicConfig(level=logging.DEBUG)
        Database.DEFAULT_FILENAME = str(args.database)
        config = Config(args.config)
        app.piju_config = config
        app.work_queue = Queue()
        app.worker = WorkerThread(app.work_queue)
        app.worker.start()
        app.file_player = FilePlayer(mp3audiodevice=args.mp3audiodevice)
        app.stream_player = StreamPlayer(audio_device=args.mp3audiodevice)
        app.current_player = app.file_player
        app.api_version_string = '6.0'
        app.download_history = DownloadHistory()
        app.register_blueprint(routes)
        # macOS: Need to disable AirPlay Receiver for listening on 0.0.0.0 to work
        # see https://developer.apple.com/forums/thread/682332
        app.run(use_reloader=False, host='0.0.0.0', threaded=True)


if __name__ == '__main__':
    main()
