import json
import logging
import os.path
import socket
import subprocess
import threading
import time


class ChildMonitorThread(threading.Thread):
    def __init__(self, child, callback):
        self.child = child
        self.callback = callback
        self.should_terminate = threading.Event()
        super().__init__()

    def run(self):
        while (self.child.poll() is None) and (not self.should_terminate.is_set()):
            time.sleep(1)
        print(f"Monitor: end detected (or terminated). Callback {'enabled' if self.callback else 'suppressed'}")
        if self.child.poll() is not None:
            if self.callback:
                self.callback()


class MPVMusicPlayer:
    @staticmethod
    def encode_command(command):
        command = {'command': command}
        command = json.dumps(command) + '\n'
        command = command.encode()
        return command

    def __init__(self, parent):
        self.parent = parent
        self.ipc_address = '/tmp/piju.mpv-socket'
        self.exe = 'mpv'  # TODO: Config needed?

        self.pause_cmd = MPVMusicPlayer.encode_command(['set_property_string', 'pause', 'yes'])
        self.resume_cmd = MPVMusicPlayer.encode_command(['set_property_string', 'pause', 'no'])
        self.child = None
        self.sock = None
        self.monitor = None

        if os.path.exists(self.ipc_address):
            os.remove(self.ipc_address)

    def __del__(self):
        self.stop()
        if os.path.exists(self.ipc_address):
            os.remove(self.ipc_address)

    def _send_command(self, command, timeout=0.5):
        if not self.child:
            return
        if self.sock is None:
            self.sock = socket.socket(socket.AF_UNIX)
            end = time.time() + timeout
            connected = False
            while (not connected) and (time.time() < end):
                try:
                    self.sock.connect(self.ipc_address)
                    connected = True
                except (FileNotFoundError, ConnectionRefusedError):
                    logging.debug("No socket found for MPV IPC")
            if not connected:
                logging.debug("Connection timeout")
                self.sock = None
                return

        logging.debug("MPVPlayer.send_command %s", command)
        self.sock.sendall(command)

    def pause(self):
        logging.debug("MPVPlayer.pause")
        self._send_command(self.pause_cmd)

    def play_song(self, filepath: str):
        self.sock = None
        cmd = [self.exe, '--really-quiet', '--no-video', f'--input-ipc-server={self.ipc_address}', filepath]
        logging.debug(f'MPVPlayer._play: {" ".join(cmd)}')
        self.child = subprocess.Popen(cmd, stdout=subprocess.DEVNULL)
        # Ensure we notice when the child finishes:
        self.monitor = ChildMonitorThread(self.child, self.parent.on_music_end)
        self.monitor.start()

    def resume(self):
        logging.debug("MPVPlayer.resume")
        self._send_command(self.resume_cmd)

    def set_volume(self, volume):
        logging.debug(f"MPVPlayer.set_volume {volume}")
        self._send_command(MPVMusicPlayer.encode_command(['set_property', 'volume', volume]))

    def stop(self):
        if self.monitor:
            self.monitor.callback = None
            self.monitor.should_terminate.set()
        if self.child:
            self.child.kill()
            self.child = None
