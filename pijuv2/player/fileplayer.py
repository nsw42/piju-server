from collections import namedtuple
import logging
import os.path
import time
from typing import List, Optional

from .mp3player import MP3MusicPlayer
from .mpvmusicplayer import MPVMusicPlayer
from .playerinterface import CurrentStatusStrings, PlayerInterface

from ..database.schema import Track


QueuedTrack = namedtuple('QueuedTrack', 'filepath, trackid, artist, title, artwork')
# filepath: str
# trackid: int
# artist: str
# title: str
# artwork: str


class FilePlayer(PlayerInterface):
    def __init__(self, queue: List[Track] = None, identifier: str = '', mp3audiodevice=None):
        super().__init__()
        self.queue = []
        self.current_tracklist_identifier = identifier
        self.set_queue(queue, identifier)
        self.current_player = None
        self.index = None
        self.mp3audiodevice = mp3audiodevice

    @property
    def current_track(self) -> QueuedTrack:
        return None if self.index is None else self.queue[self.index]

    @property
    def maximum_track_index(self) -> int:
        return len(self.queue) if self.queue else None

    @property
    def visible_queue(self):
        return [] if self.index is None else self.queue[self.index:]

    def _play_song(self, filename: str):
        """
        Do the work of launching an appropriate player for the given file,
        including stopping any current player.
        Returns True if it started playing successfully.
        Returns False if the file doesn't exist, and leaves the
        current status in an indeterminate state. Either call again with a
        different file, or call stop()
        """
        was_playing = self._stop_player()
        if not os.path.isfile(filename):
            logging.warning(f"Skipping missing file {filename}")
            return False
        if was_playing:
            time.sleep(1)
        logging.debug(f"Playing {filename}")
        if filename.endswith('.mp3'):
            self.current_player = MP3MusicPlayer(self, audiodevice=self.mp3audiodevice)
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
        stopping, such as setting state variables.
        Returns whether it was previous playing
        """
        if self.current_player:
            self.current_player.stop()
            rtn = True
        else:
            rtn = False
        self.current_player = None
        return rtn

    def clear_queue(self):
        self.stop()
        self.queue = []  # list of QueuedTrack

    def set_queue(self, queue: Optional[List[Track]], identifier: str):
        if queue:
            self.queue = [QueuedTrack(track.Filepath, track.Id, track.Artist, track.Title, None) for track in queue]
        else:
            self.queue = []
        self.index = 0  # invariant: the index of the *currently playing* song
        self.current_tracklist_identifier = identifier

    def add_to_queue(self, filepath: str, track_id: int, artist: str, title: str, artwork_uri: str):
        self.queue.append(QueuedTrack(filepath, track_id, artist, title, artwork_uri))
        self.current_tracklist_identifier = "/queue/"
        # If this is the first item in the queue, start playing
        if self.index is None:
            self.play_from_real_queue_index(0)

    def remove_from_queue(self, index: int, trackid: int):
        """
        Remove the element from the player queue if it matches both index and trackid
        (avoiding the problem of the player moving onto the next track between getting the
        queue and issuing the request to delete from the queue)
        index is 0-based, representing the index into the remaining part of the queue
        trackid is the numeric track id
        """
        if self.index is not None:
            index += self.index
        if 0 <= index < len(self.queue) and self.queue[index].trackid == trackid:
            self.queue.pop(index)
            # If this is the currently playing track, jump to the next track
            # (which might result in us stopping playing completely).
            # But, the next track is at the same index we're already at -
            # we've just deleted from the list
            if index == self.index:
                self.play_from_real_queue_index(self.index)
            return True
        return False

    def play_from_apparent_queue_index(self, index, trackid: int = None):
        """
        Play from the *apparent* queue index, which is not necessarily the same as the real
        queue index. The real queue index is the list of files, eg tracks of an album.
        Items get removed from the apparent queue, as the index moves through the queue.
        """
        if self.index is not None:
            index += self.index
        return self.play_from_real_queue_index(index, trackid)

    def play_from_real_queue_index(self, index, trackid: int = None):
        """
        Play from the given index
        trackid, if given, acts as a sanity check that the desired track is going to be played.
        If the queue at index doesn't match the given trackid, the queue is checked +/- 1,
        to allow for concurrent actions, the request coinciding with the end of a track, etc.
        If the given file cannot be played, automatically moves to the next in
        Returns False if the sanity checks fail
        Returns True if it started playing a track
        """
        if trackid is not None:
            # pre-flight sanity check: inc/dec index to find the desired track
            if not ((0 <= index < len(self.queue)) and (self.queue[index].trackid == trackid)):
                if (index > 0) and (self.queue[index - 1].trackid == trackid):
                    index -= 1
                elif (index < len(self.queue) - 1) and (self.queue[index + 1].trackid == trackid):
                    index += 1
                else:
                    # We failed the sanity check - couldn't find the requested track
                    return False
        started = False
        while (0 <= index < len(self.queue)) and not (started := self._play_song(self.queue[index].filepath)):
            index += 1
        if started:
            self.index = index
            return True
        else:
            self.stop()
            return False

    def next(self):
        # play the next song in the queue
        if self.index is None:
            return
        logging.debug(f"FilePlayer.next ({self.current_player})")
        if self.index + 1 < len(self.queue):
            self.play_from_real_queue_index(self.index + 1)
        else:
            self.stop()
            self.clear_queue()

    def prev(self):
        self.play_from_real_queue_index(max(0, self.index - 1))

    # Wrapper over the lower-layer interface

    def pause(self):
        logging.debug(f"FilePlayer.pause ({self.current_player})")
        if self.current_player:
            self.current_player.pause()
        self.current_status = CurrentStatusStrings.PAUSED

    def resume(self):
        logging.debug(f"FilePlayer.resume ({self.current_player})")
        if self.current_player:
            self.current_player.resume()
        self.current_status = CurrentStatusStrings.PLAYING

    def set_volume(self, volume: int):
        logging.debug(f"FilePlayer.set_volume {volume}")
        if self.current_player:
            self.current_player.set_volume(volume)
        self.current_volume = volume

    def stop(self):
        logging.debug(f"FilePlayer.stop ({self.current_player})")
        self._stop_player()
        self.current_tracklist_identifier = ''
        self.current_status = CurrentStatusStrings.STOPPED
        self.index = None

    # callbacks
    def on_music_end(self):
        # maybe flush the queue at the end??
        logging.debug(f"FilePlayer.on_music_end ({self.current_player})")
        self.next()
