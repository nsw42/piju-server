import logging
import os.path
from typing import List

from .mp3player import MP3MusicPlayer
from .mpvmusicplayer import MPVMusicPlayer

from ..database.schema import Track


class MusicPlayer:
    def __init__(self, queue: List[Track] = [], identifier: str = ''):
        self.set_queue(queue, identifier)
        self.current_player = None
        self.current_status = 'stopped'
        self.current_volume = 100

    def _play_song(self, filename: str):
        """
        Do the work of launching an appropriate player for the given file,
        including stopping any current player.
        Returns True if it started playing successfully.
        Returns False if the file doesn't exist, and leaves the
        current status in an indeterminate state. Either call again with a
        different file, or call stop()
        """
        logging.debug(f"Playing {filename}")
        self._stop_player()
        if not os.path.isfile(filename):
            return False
        if filename.endswith('.mp3'):
            self.current_player = MP3MusicPlayer(self)
            self.current_player.play_song(filename)
        else:
            self.current_player = MPVMusicPlayer(self)
            self.current_player.play_song(filename)
        self.current_player.set_volume(self.current_volume)
        self.current_status = 'playing'
        return True

    def _stop_player(self):
        """
        Stop the music player only - i.e. don't do the rest of the actions normally associated with
        stopping, such as setting state variables
        """
        if self.current_player:
            self.current_player.stop()
        self.current_player = None

    def clear_queue(self):
        self.queued_files = []
        self.queued_track_ids = []
        self.index = 0
        self.current_tracklist_identifier = ''

    def set_queue(self, queue: List[Track], identifier: str):
        self.queued_files = [track.Filepath for track in queue]
        self.queued_track_ids = [track.Id for track in queue]
        self.index = 0  # invariant: the index of the *currently playing* song
        self.current_track_id = self.queued_track_ids[0] if self.queued_track_ids else None
        self.current_tracklist_identifier = identifier

    def play_from_queue_index(self, index):
        started = False
        while (index < len(self.queued_files)) and not (started := self._play_song(self.queued_files[index])):
            index += 1
        if started:
            self.current_track_id = self.queued_track_ids[index]
            self.index = index
        else:
            self.stop()

    def play_track(self, track: Track):
        if self._play_song(track.Filepath):
            self.current_track_id = track.Id
        else:
            self.stop()

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

    # Wrapper over the lower-layer interface

    def pause(self):
        logging.debug(f"MusicPlayer.pause ({self.current_player})")
        if self.current_player:
            self.current_player.pause()
        self.current_status = 'paused'

    def resume(self):
        logging.debug(f"MusicPlayer.resume ({self.current_player})")
        if self.current_player:
            self.current_player.resume()
        self.current_status = 'playing'

    def set_volume(self, volume: int):
        logging.debug(f"MusicPlayer.set_volume {volume}")
        if self.current_player:
            self.current_player.set_volume(volume)
        self.current_volume = volume

    def stop(self):
        logging.debug(f"MusicPlayer.stop ({self.current_player})")
        self._stop_player()
        self.current_track_id = None
        self.current_tracklist_identifier = ''
        self.current_status = 'stopped'

    # callbacks
    def on_music_end(self):
        # maybe flush the queue at the end??
        self.next()
