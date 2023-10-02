from collections import namedtuple
import logging
import os.path
import time
from typing import List, Union

from .mp3player import MP3MusicPlayer
from .mpvmusicplayer import MPVMusicPlayer
from .playerinterface import CurrentStatusStrings, PlayerInterface

from ..backend.downloadinfo import DownloadInfo  # TODO: Layering is a mess
from ..database.schema import Track


QueuedTrack = namedtuple('QueuedTrack', 'filepath, trackid, artist, title, artwork')
# filepath: str
# trackid: int - negative for YouTube files; non-negative for Tracks from the database
# artist: str
# title: str
# artwork: str - only for YouTube files (and even then may be unknown); is always None for Tracks from the database


class FilePlayer(PlayerInterface):
    def __init__(self, queue: List[Track] = None, identifier: str = '', mp3audiodevice=None):
        super().__init__()
        self.queue = []  # list of QueuedTrack
        self.current_tracklist_identifier = identifier
        self.current_player = None
        self.mp3audiodevice = mp3audiodevice
        self.set_queue(queue, identifier)

    @property
    def current_track(self) -> QueuedTrack:
        return None if self.current_track_index is None else self.queue[self.current_track_index]

    @property
    def number_of_tracks(self) -> int:
        return len(self.queue) if self.queue else None

    @property
    def visible_queue(self):
        return [] if self.current_track_index is None else self.queue[self.current_track_index:]

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
        self.current_track_index = None

    def set_queue(self, new_queue: List[Union[DownloadInfo, Track]], identifier: str):
        if new_queue:
            currently_playing = None if (self.current_track_index is None) else self.queue[self.current_track_index]
            self.queue = []
            for item in new_queue:
                if isinstance(item, DownloadInfo):
                    queue_item = QueuedTrack(str(item.filepath),
                                             item.fake_trackid,
                                             item.artist,
                                             item.title,
                                             item.artwork)
                else:
                    queue_item = QueuedTrack(item.Filepath,
                                             item.Id,
                                             item.Artist,
                                             item.Title,
                                             None)
                self.queue.append(queue_item)
            self.current_track_index = 0  # invariant: the index of the *currently playing* song
            if (not currently_playing) or (currently_playing.trackid != self.queue[0].trackid):
                self.play_from_real_queue_index(0)
        else:
            self.clear_queue()
        self.current_tracklist_identifier = identifier

    def add_to_queue(self, filepath: str, track_id: int, artist: str, title: str, artwork_uri: str):
        self.queue.append(QueuedTrack(filepath, track_id, artist, title, artwork_uri))
        self.current_tracklist_identifier = "/queue/"
        # If this is the first item in the queue, start playing
        if self.current_track_index is None:
            self.play_from_real_queue_index(0)

    def remove_from_queue(self, index: int, trackid: int):
        """
        Remove the element from the player queue if it matches both index and trackid
        (avoiding the problem of the player moving onto the next track between getting the
        queue and issuing the request to delete from the queue)
        index is 0-based, representing the index into the remaining part of the queue
        trackid is the numeric track id
        """
        if self.current_track_index is not None:
            index += self.current_track_index
        if 0 <= index < len(self.queue) and self.queue[index].trackid == trackid:
            self.queue.pop(index)
            # If this is the currently playing track, jump to the next track
            # (which might result in us stopping playing completely).
            # But, the next track is at the same index we're already at -
            # we've just deleted from the list
            if index == self.current_track_index:
                self.play_from_real_queue_index(self.current_track_index)
            return True
        return False

    def play_from_apparent_queue_index(self, index, trackid: int = None):
        """
        Play from the *apparent* queue index, which is not necessarily the same as the real
        queue index. The real queue index is the list of files, eg tracks of an album.
        Items get removed from the apparent queue, as the index moves through the queue.
        """
        if self.current_track_index is not None:
            index += self.current_track_index
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
            self.current_track_index = index
            return True
        else:
            self.stop()
            return False

    def next(self):
        # play the next song in the queue
        if self.current_track_index is None:
            return
        logging.debug(f"FilePlayer.next ({self.current_player})")
        if self.current_track_index + 1 < len(self.queue):
            self.play_from_real_queue_index(self.current_track_index + 1)
        else:
            self.stop()
            self.clear_queue()

    def prev(self):
        self.play_from_real_queue_index(max(0, self.current_track_index - 1))

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
        self.current_track_index = None

    # callbacks
    def on_music_end(self):
        # maybe flush the queue at the end??
        logging.debug(f"FilePlayer.on_music_end ({self.current_player})")
        self.next()
