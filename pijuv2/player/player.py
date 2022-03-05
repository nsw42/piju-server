from typing import List

from .mpyg321 import MPyg321Player, PlayerStatus

from ..database.schema import Track


class MusicPlayer(MPyg321Player):
    def __init__(self, queue: List[Track] = []):
        self.set_queue(queue)
        super().__init__()
        self.volume(100)

    def set_queue(self, queue: List[Track]):
        self.queued_files = [track.Filepath for track in queue]
        self.queued_track_ids = [track.Id for track in queue]
        self.index = 0  # invariant: the index of the *currently playing* song
        self.current_track_id = self.queued_track_ids[0] if self.queued_track_ids else None

    def play_from_queue_index(self, index):
        assert 0 <= index < len(self.queued_files)
        self.play_song(self.queued_files[index])
        self.current_track_id = self.queued_track_ids[index]
        self.index = index

    def next(self):
        # play the next song in the queue
        if self.index + 1 < len(self.queued_files):
            self.play_from_queue_index(self.index + 1)
        else:
            self.stop()

    def prev(self):
        if True:
            self.play_from_queue_index(max(0, self.index - 1))
        else:
            if 0 < self.index:
                self.play_from_queue_index(self.index - 1)
            else:
                self.stop()

    def playpause(self):
        if self.status == PlayerStatus.PLAYING:
            self.pause()
        else:
            self.resume()

    def stop(self):
        super().stop()
        self.current_track_id = None

    # callbacks
    def on_music_end(self):
        # maybe flush the queue at the end??
        self.next()
