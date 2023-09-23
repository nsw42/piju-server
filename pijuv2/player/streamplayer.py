import json
import logging
import os
import subprocess
from threading import Thread
from time import sleep, time
from typing import Optional

import requests

from .playerinterface import CurrentStatusStrings, PlayerInterface


class NowPlayingUpdater(Thread):
    def __init__(self, parent: 'StreamPlayer'):
        super().__init__(name="Now Playing Updater thread", target=self.run, daemon=True)
        self.parent = parent
        self.start()

    def run(self):
        next_fetch_track_info = next_fetch_artwork_info = time()  # fetch as soon as we start playing
        while True:
            now = time()
            if self.parent.current_status != CurrentStatusStrings.PLAYING:
                next_check = now + 10
            else:
                if now >= next_fetch_track_info:
                    next_fetch_track_info = now + self.do_one_fetch_track_info()
                if now >= next_fetch_artwork_info:
                    next_fetch_artwork_info = now + self.do_one_fetch_artwork_info()
                next_check = min(next_fetch_track_info, next_fetch_artwork_info)
            sleep(next_check - now)

    def do_one_fetch_track_info(self):
        """
        Return the number of seconds to wait before trying again
        """
        if not self.parent.get_track_info_url:
            # nothing playing right now
            return 60
        text = self.fetch_and_jq(self.parent.get_track_info_url, self.parent.get_track_info_jq, raw=False)

        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                logging.debug("Data in wrong format. Discarding")
                data = {}
        except json.JSONDecodeError:
            logging.debug(f"JSON decode error: could not decode: {text}")
            data = {}
        self.parent.now_playing_artist = data.get('artist')
        self.parent.now_playing_track = data.get('track')
        if self.parent.now_playing_artist and self.parent.now_playing_track:
            return 60
        return 30

    def do_one_fetch_artwork_info(self):
        """
        Return the number of seconds to wait before trying again
        """
        if self.parent.get_artwork_url:
            url = self.fetch_and_jq(self.parent.get_artwork_url, self.parent.get_artwork_jq, raw=True)
        else:
            url = None
        if url:
            self.parent.currently_playing_artwork = url
            return 60
        self.parent.currently_playing_artwork = self.parent.station_artwork
        return 30

    def fetch_and_jq(self, url: str, jq_filter: Optional[str], raw: bool):
        """
        Fetch the given url and transform it with the given jq filter
        """
        response = requests.get(url, timeout=30)
        if not response.ok:
            logging.debug(f"requests.get failed: {response.status_code}")
            return 30

        logging.debug(f"Fetched text: {response.text}")
        if jq_filter:
            # content needs to be filtered
            logging.debug(f"{jq_filter}")
            cmd = ['jq']
            if raw:
                cmd.append('-r')
            cmd.append(jq_filter)
            child = subprocess.run(cmd,
                                   input=response.text,
                                   capture_output=True,
                                   check=False,  # if it fails, empty output will be fine
                                   text=True)
            if child.returncode == 0:
                text = child.stdout.strip()
                logging.debug(f"Filtered text: {text}")
                if text == 'null':
                    # A jq filter problem
                    text = ''
            else:
                logging.debug("jq failed")
                text = ''
        else:
            # content is apparently already in the correct form
            text = response.text
        return text


class StreamPlayer(PlayerInterface):
    def __init__(self, audio_device: str):
        super().__init__()
        self.currently_playing_name = None
        self.currently_playing_url = None
        self.currently_playing_artwork = None
        self.station_artwork = None
        self.number_of_tracks = None
        self.get_track_info_url = None
        self.get_track_info_jq = None
        self.get_artwork_url = None
        self.get_artwork_jq = None
        self.player_subprocess = None
        self.audio_device = audio_device
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
        if self.audio_device:
            child_environment = dict(os.environ)
            child_environment['SDL_AUDIODRIVER'] = 'alsa'
            child_environment['AUDIODEV'] = self.audio_device
        else:
            child_environment = None
        self.player_subprocess = subprocess.Popen(cmd, env=child_environment)

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
        self.current_status = CurrentStatusStrings.PLAYING
        self.currently_playing_name = name
        self.currently_playing_url = url
        self.station_artwork = self.currently_playing_artwork = station_artwork
        self.current_track_index = current_index
        self.number_of_tracks = nr_stations
        self.get_track_info_url = get_track_info_url
        self.get_track_info_jq = get_track_info_jq
        self.get_artwork_url = get_artwork_url
        self.get_artwork_jq = get_artwork_jq
        self._play()

    def pause(self):
        """
        Required for interface compatibility but we cannot actually
        pause. So just stop, but make it look like we've paused.
        """
        self._stop()
        self.current_status = CurrentStatusStrings.PAUSED

    def resume(self):
        """
        Like pause(), required for interface compatibility.
        Restarts playing the last url that was played.
        """
        if self.currently_playing_name:
            self._play()

    def stop(self):
        self._stop()
        self.current_status = CurrentStatusStrings.STOPPED
        self.currently_playing_name = self.currently_playing_url = self.currently_playing_artwork = None
        self.current_track_index = self.number_of_tracks = None
        self.get_track_info_url = self.get_track_info_jq = self.now_playing_artist = self.now_playing_track = None

    def set_volume(self, volume):
        self.current_volume = volume
