from collections import defaultdict
import json
import logging
import math
import subprocess
from threading import Thread
import time
from typing import Optional

import requests

from .playerinterface import CurrentStatusStrings, PlayerInterface


def fetch(url: str) -> Optional[str]:
    """
    Fetch the data from the given url and return it as plaintext.
    Returns None if the fetch failed
    """
    try:
        response = requests.get(url, timeout=30)
        if not response.ok:
            logging.debug(f"requests.get failed: {response.status_code}")
            return None
    except (requests.ConnectionError, requests.Timeout) as e:
        logging.warning(f"requests.get failed: {e}")
        return None
    logging.debug(f"Fetched text: {response.text}")
    return response.text


def jq(data: str, jq_filter: str) -> Optional[str]:
    """
    Run the given string through jq, with the given filter, and return the result
    as a JSON-decoded object.
    Returns None if jq fails.
    """
    logging.debug(f"{jq_filter}")
    cmd = ['jq', jq_filter]
    child = subprocess.run(cmd,
                           input=data,
                           capture_output=True,
                           check=False,  # if it fails, empty output will be fine
                           text=True)
    if child.returncode != 0:
        logging.debug("jq failed")
        return None

    text = child.stdout.strip()
    logging.debug(f"Filtered text: {text}")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        logging.debug(f"JSON decode error: could not decode: {text}")
        return None
    if value == 'null':
        # Possibly a jq filter problem, or possibly no relevant information available at the moment
        return None
    return value


class MinimumSeen:
    def __init__(self):
        self.value = None

    def update(self, v):
        self.value = v if (self.value is None) else min(v, self.value)


class NowPlayingUpdater(Thread):
    def __init__(self, parent: 'StreamPlayer'):
        super().__init__(name="Now Playing Updater thread", target=self.run, daemon=True)
        self.parent = parent
        self.next_fetch = time.monotonic()
        self.start()

    def show_not_playing(self):
        for _, updates in self.parent.dynamic_info.items():
            for _, save_results in updates:
                save_results(None)

    def do_all_fetches(self):
        # Return the amount of time until we need to fetch again
        min_delta = MinimumSeen()
        for url, updates in self.parent.dynamic_info.items():
            data = fetch(url)
            if data:
                for jq_filter, save_results in updates:
                    filtered_data = jq(data, jq_filter) if jq_filter else data
                    delta = save_results(filtered_data)
                    min_delta.update(delta)
            else:
                # ensure we don't show out-of-date information, but try again soon
                for _, save_results in updates:
                    save_results(None)
                min_delta.update(10)
        return min_delta.value or 10

    def state_change(self, new_status):
        if new_status == CurrentStatusStrings.PLAYING:
            self.next_fetch = time.monotonic()  # fetch as soon as the thread updates
        else:
            self.show_not_playing()
            self.next_fetch = math.inf

    def run(self):
        while True:
            now = time.monotonic()

            if now >= self.next_fetch:
                self.next_fetch = now + self.do_all_fetches()

            time.sleep(3)


class StreamPlayer(PlayerInterface):
    def __init__(self):
        super().__init__()
        self.currently_playing_name = None
        self.currently_playing_url = None
        self.currently_playing_artwork = None
        self.station_artwork = None
        self.number_of_tracks = None
        self.dynamic_info = {}
        self.player_subprocess = None
        self.now_playing_artist = None  # updated by the NowPlayingUpdater
        self.now_playing_track = None  # updated by the NowPlayingUpdater
        self.update_now_playing_thread = NowPlayingUpdater(self)

    def _stop(self):
        """
        Stop playback, but don't clear metadata, supporting both stop() and pause()
        """
        if self.player_subprocess:
            self.player_subprocess.terminate()
        self.player_subprocess = None

    def _play(self):
        # -nodisp: disable graphical display
        # -vn: disable video
        # -sn: disable subtitles
        if self.player_subprocess:
            self._stop()
        cmd = ['ffplay', '-nodisp', '-vn', '-sn',
               '-volume', str(self.current_volume),
               '-loglevel', 'warning',
               self.currently_playing_url]
        self.player_subprocess = subprocess.Popen(cmd)
        self.current_status = CurrentStatusStrings.PLAYING

    def play(self,
             name: str,
             url: str,
             station_artwork: str,
             current_index: int,
             nr_stations: int,
             get_track_info_url: str,
             get_track_info_jq: str,
             get_artwork_url: str,
             get_artwork_jq: str):
        self.currently_playing_name = name
        self.currently_playing_url = url
        self.station_artwork = self.currently_playing_artwork = station_artwork
        self.current_track_index = current_index
        self.number_of_tracks = nr_stations
        self.dynamic_info = defaultdict(list)
        self.dynamic_info[get_track_info_url].append((get_track_info_jq, self.set_track_info))
        self.dynamic_info[get_artwork_url].append((get_artwork_jq, self.set_artwork))
        self.now_playing_artist = self.now_playing_track = None
        self._play()
        self.send_now_playing_update()
        self.update_now_playing_thread.state_change(self.current_status)

    def set_track_info(self, track_info):
        if track_info is None:
            track_info = {}
        if not isinstance(track_info, dict):
            logging.debug("Data in wrong format. Discarding")
            track_info = {}
        old_artist = self.now_playing_artist
        old_track = self.now_playing_track
        self.now_playing_artist = track_info.get('artist')
        self.now_playing_track = track_info.get('track')
        if (self.now_playing_artist != old_artist) or (self.now_playing_track != old_track):
            self.send_now_playing_update()
        if self.now_playing_artist and self.now_playing_track:
            return 60
        return 30

    def set_artwork(self, artwork_url):
        if artwork_url and not isinstance(artwork_url, str):
            logging.debug("Data in wrong format. Discarding")
            artwork_url = None
        old_val = self.currently_playing_artwork
        if artwork_url:
            self.currently_playing_artwork = artwork_url
            next_call = 60
        else:
            self.currently_playing_artwork = self.station_artwork
            next_call = 30
        if self.currently_playing_artwork != old_val:
            self.send_now_playing_update()
        return next_call

    def pause(self):
        """
        Required for interface compatibility but we cannot actually
        pause. So just stop, but make it look like we've paused.
        """
        self._stop()
        self.current_status = CurrentStatusStrings.PAUSED
        self.currently_playing_artwork = self.station_artwork
        self.send_now_playing_update()
        self.update_now_playing_thread.state_change(self.current_status)

    def resume(self):
        """
        Like pause(), required for interface compatibility.
        Restarts playing the last url that was played.
        """
        if self.currently_playing_name:
            self._play()
            self.send_now_playing_update()
            self.update_now_playing_thread.state_change(self.current_status)

    def stop(self):
        self._stop()
        self.current_status = CurrentStatusStrings.STOPPED
        self.currently_playing_name = self.currently_playing_url = self.currently_playing_artwork = None
        self.current_track_index = self.number_of_tracks = None
        self.now_playing_artist = self.now_playing_track = None
        self.dynamic_info = {}
        self.send_now_playing_update()
        self.update_now_playing_thread.state_change(self.current_status)

    def set_volume(self, volume):
        # Cannot (yet?) change the volume of a running player, but we can at least
        # save the correct volume in case we pause/resume
        self.current_volume = volume
        self.send_now_playing_update()
