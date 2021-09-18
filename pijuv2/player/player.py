from .mpyg321 import MPyg321Player, PlayerStatus

from ..database.schema import Track


class MusicPlayer(MPyg321Player):
    def __init__(self, queue=[]):
        self.set_queue(queue)
        super().__init__()

    def set_queue(self, queue):
        self.queue = []
        for track in queue:
            if isinstance(track, Track):
                self.queue.append(track.Filepath)
            elif isinstance(track, str):
                self.queue.append(track)
            else:
                assert False  # TODO
        self.index = 0  # invariant: the index of the *currently playing* song

    def play_from_queue_index(self, index):
        assert 0 <= index < len(self.queue)
        self.play_song(self.queue[index])
        self.index = index

    def next(self):
        # play the next song in the queue
        if self.index + 1 < len(self.queue):
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

    # callbacks
    def on_music_end(self):
        # maybe flush the queue at the end??
        self.next()
