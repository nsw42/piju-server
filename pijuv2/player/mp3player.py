from .mpyg321 import MPyg321Player, PlayerStatus


class MP3MusicPlayer(MPyg321Player):
    def __init__(self, parent):
        super().__init__()
        self.volume(100)
        self.parent = parent

    def playpause(self):
        if self.status == PlayerStatus.PLAYING:
            self.pause()
        else:
            self.resume()

    def set_volume(self, volume: int):
        self.volume(volume)

    def stop(self):
        super().quit()

    # callbacks
    def on_music_end(self):
        self.parent.on_music_end()
