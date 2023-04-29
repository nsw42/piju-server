from collections import namedtuple
import logging
import os.path
from typing import List

from .mp3player import MP3MusicPlayer
from .mpvmusicplayer import MPVMusicPlayer

from ..database.schema import Track


QueuedTrack = namedtuple('QueuedTrack', 'filepath, trackid')


class MusicPlayer:
    def __init__(self, queue: List[Track] = [], identifier: str = ''):
        self.set_queue(queue, identifier)
        self.current_player = None
        self.current_status = 'stopped'
        self.current_volume = 100
        self.index = None

    @property
    def maximum_track_index(self):
        return len(self.queue) if self.queue else None

    def _play_song(self, filename: str):
        """
        Do the work of launching an appropriate player for the given file,
        including stopping any current player.
        Returns True if it started playing successfully.
        Returns False if the file doesn't exist, and leaves the
        current status in an indeterminate state. Either call again with a
        different file, or call stop()
        """
        self._stop_player()
        if not os.path.isfile(filename):
            logging.warning(f"Skipping missing file {filename}")
            return False
        logging.debug(f"Playing {filename}")
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
        self.queue = []  # list of QueuedTrack
        self.index = None
        self.current_tracklist_identifier = ''

    def set_queue(self, queue: List[Track], identifier: str):
        self.queue = [QueuedTrack(track.Filepath, track.id) for track in queue]
        self.index = 0  # invariant: the index of the *currently playing* song
        self.current_track_id = self.queue[0].trackid if self.queue else None
        self.current_tracklist_identifier = identifier

    def get_queued_track_ids(self):
        return [qe.trackid for qe in self.queue[self.index:]]

    def add_to_queue(self, **kwargs):
        if track := kwargs.get('track'):
            self.queue.append(QueuedTrack(track.Filepath, track.Id))
        elif filepath := kwargs.get('filepath'):
            self.queue.append(QueuedTrack(filepath, None))
        else:
            raise Exception("keyword arguments track or filepath are mandatory")
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
            self.current_track_id = self.queue[index].trackid
            self.index = index
            return True
        else:
            self.stop()
            return False

    def play_file(self, path: str):
        if self._play_song(path):
            # TODO: Save more information about what's being played
            self.current_track_id = None
        else:
            self.stop()

    def play_track(self, track: Track):
        if self._play_song(track.Filepath):
            self.current_track_id = track.Id
        else:
            self.stop()

    def next(self):
        # play the next song in the queue
        if self.index is None:
            return
        logging.debug(f"MusicPlayer.next ({self.current_player})")
        if self.index + 1 < len(self.queue):
            self.play_from_real_queue_index(self.index + 1)
        else:
            self.stop()
            self.clear_queue()

    def prev(self):
        self.play_from_real_queue_index(max(0, self.index - 1))

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
        self.index = None

    # callbacks
    def on_music_end(self):
        # maybe flush the queue at the end??
        logging.debug(f"MusicPlayer.on_music_end ({self.current_player})")
        self.next()
