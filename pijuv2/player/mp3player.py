import logging

from .mpyg321 import MPyg321Player, PlayerStatus


class MP3MusicPlayer(MPyg321Player):
    def __init__(self, parent, start_background_task):
        super().__init__(start_background_task)
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
        logging.debug(f"MP3MusicPlayer.stop ({self})")
        super().quit()

    # callbacks
    def on_music_end(self):
        logging.debug(f"MP3MusicPlayer.on_music_end ({self})")
        self.parent.on_music_end()
