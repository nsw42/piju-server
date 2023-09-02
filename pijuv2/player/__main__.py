from argparse import ArgumentParser
import logging
import time

from ..database.database import DatabaseAccess
from .fileplayer import FilePlayer


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('tracks', type=int, nargs='+')
    parser.set_defaults(debug=False, tracks=[])
    args = parser.parse_args()
    return args


def main():
    args = parse_args()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    with DatabaseAccess() as db:
        tracks = [db.get_track_by_id(tid) for tid in args.tracks]
    player = FilePlayer(tracks)
    player.play_from_real_queue_index(0)
    while player.current_status != 'stopped':
        time.sleep(1)


if __name__ == '__main__':
    main()
