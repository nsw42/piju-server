import sys
import time

from ..database.database import DatabaseAccess
from .player import MusicPlayer


if __name__ == '__main__':
    track_ids = map(int, sys.argv[1:])
    with DatabaseAccess() as db:
        tracks = [db.get_track_by_id(tid) for tid in track_ids]
    player = MusicPlayer(tracks)
    player.play_from_queue_index(0)
    while player.current_status != 'stopped':
        time.sleep(1)
