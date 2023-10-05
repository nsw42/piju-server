from argparse import ArgumentParser
import logging
import mimetypes
from pathlib import Path

from ..database.database import Database
from .appfactory import create_app
from .config import Config


# HELPER FUNCTIONS ----------------------------------------------------------------------------

def parse_args():
    parser = ArgumentParser()
    parser.add_argument('-a', '--mp3audiodevice', action='store',
                        help='Set audio device for mpg123')
    parser.add_argument('-c', '--config', metavar='FILE', type=Path,
                        help=f"Load configuration from FILE. Default is {str(Config.default_filepath())}")
    parser.add_argument('-d', '--database', metavar='FILE', type=Path,
                        help="Set database path to FILE. Default is %(default)s")
    parser.set_defaults(config=None,
                        database='file.db')
    args = parser.parse_args()
    if args.config and not args.config.is_file():
        parser.error(f"Specified configuration file ({str(args.config)}) could not be found")
    if (args.config is None) and (Config.default_filepath().is_file()):
        args.config = Config.default_filepath()
    if not args.database.is_file():
        parser.error("Specified database file does not exist. Use `run.sh` (or alembic) to initialise the database")
    return args


# MAIN --------------------------------------------------------------------------------------------

def main():
    args = parse_args()

    logging.basicConfig(level=logging.DEBUG)
    Database.DEFAULT_URI = Database.SQLITE_PREFIX + str(args.database)
    app = create_app()
    app.worker.start()
    mimetypes.init()
    # macOS: Need to disable AirPlay Receiver for listening on 0.0.0.0 to work
    # see https://developer.apple.com/forums/thread/682332
    app.run(use_reloader=False, host='0.0.0.0', threaded=True)


if __name__ == '__main__':
    main()
