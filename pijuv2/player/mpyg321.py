from enum import Enum
import pexpect
import re
from threading import Thread


class MpgOutputAction(Enum):
    MUSIC_STOP = 0
    USER_PAUSE = 1
    USER_START_OR_RESUME = 2
    END_OF_SONG = 3
    ERROR = 4
    FRAME_UPDATE = 5
    INFORMATION = 6


mpg_outs = [
    {
        "mpg_code": "@P 0",
        "action": MpgOutputAction.MUSIC_STOP,
        "description": """For mpg123, it corresponds to any stop
                        For mpg321 it corresponds to user stop only"""
    },
    {
        "mpg_code": "@P 1",
        "action": MpgOutputAction.USER_PAUSE,
        "description": "Music has been paused by the user."
    },
    {
        "mpg_code": "@P 2",
        "action": MpgOutputAction.USER_START_OR_RESUME,
        "description": "Music has been started resumed by the user."
    },
    {
        "mpg_code": "@P 3",
        "action": MpgOutputAction.END_OF_SONG,
        "description": "Player has reached the end of the song."
    },
    {
        "mpg_code": "@E *",
        "action": MpgOutputAction.ERROR,
        "description": "Player has encountered an error."
    },
    {
        "mpg_code": "@F ([0-9]+) +([0-9]+) +([0-9.]+) +([0-9.]+)\r\n",
        "action": MpgOutputAction.FRAME_UPDATE,
        "description": "Frame decoding status update."
    },
    {
        "mpg_code": "@silence",
        "action": None,
        "description": "Player has been silenced by the user."
    },
    {
        "mpg_code": r"@V [0-9\.\s%]*",
        "action": None,
        "description": "Volume change event.",
    },
    {
        "mpg_code": r"@S [a-zA-Z0-9\.\s-]*",
        "action": None,
        "description": "Stereo info event."
    },
    {
        "mpg_code": r"@I [^\r\n]*\r\n",
        "action": MpgOutputAction.INFORMATION,
        "description": "Information event."
    },
    {
        "mpg_code": pexpect.TIMEOUT,
        "action": None,
        "description": "Timeout event."
    },
]

mpg_codes = [v["mpg_code"] for v in mpg_outs]

mpg_errors = [
    {
        "message": "empty list name",
        "action": "generic_error"
    },
    {
        "message": "No track loaded!",
        "action": "generic_error"
    },
    {
        "message": "Error opening stream",
        "action": "file_error"
    },
    {
        "message": "failed to parse given eq file:",
        "action": "file_error"
    },
    {
        "message": "Corrupted file:",
        "action": "file_error"
    },
    {
        "message": "Unknown command:",
        "action": "command_error"
    },
    {
        "message": "Unfinished command:",
        "action": "command_error"
    },
    {
        "message": "Unknown command or no arguments:",
        "action": "argument_error"
    },
    {
        "message": "invalid arguments for",
        "action": "argument_error"
    },
    {
        "message": "Missing argument to",
        "action": "argument_error"
    },
    {
        "message": "failed to set eq:",
        "action": "eq_error"
    },
    {
        "message": "Error while seeking",
        "action": "seek_error"
    },
]


# # # Errors # # #
class MPyg321Error(RuntimeError):
    """Base class for any errors encountered by the player during runtime"""
    pass


class MPyg321FileError(MPyg321Error):
    """Errors encountered by the player related to files"""
    pass


class MPyg321CommandError(MPyg321Error):
    """Errors encountered by the player related to player commands"""
    pass


class MPyg321ArgumentError(MPyg321Error):
    """Errors encountered by the player related to arguments for commands"""
    pass


class MPyg321EQError(MPyg321Error):
    """Errors encountered by the player related to the equalizer"""
    pass


class MPyg321SeekError(MPyg321Error):
    """Errors encountered by the player related to the seek"""
    pass


class MPyg321WrongPlayerPathError(MPyg321Error):
    """Errors encountered when a wrong player path is provided in the
    constructor"""
    pass


class MPyg321NoPlayerFoundError(MPyg321Error):
    """Errors encountered when no suitable player is found"""
    pass


class PlayerStatus(Enum):
    INSTANCIATED = 0
    PLAYING = 1
    PAUSED = 2
    RESUMING = 3
    STOPPING = 4
    STOPPED = 5
    QUITTED = 6


class MPyg321Player:
    """Main class for mpg321 player management"""
    player = None
    player_name = "mpg123"
    status = None
    output_processor = None
    song_path = ""
    loop = False
    performance_mode = True
    current_position = None

    def __init__(self, player=None, audiodevice=None, performance_mode=True):
        """Builds the player and creates the callbacks"""
        self.set_player(player, audiodevice)
        self.output_processor = Thread(target=self.process_output)
        self.output_processor.daemon = True
        self.performance_mode = performance_mode
        self.output_processor.start()
        self.silence_mpyg_output()

    def set_version_and_get_player(self, player):
        """Gets the player """
        version_process = None
        valid_player = None
        if player is not None:
            try:
                version_process = pexpect.spawn(str(player) + " --version")
                valid_player = str(player)
            except pexpect.exceptions.ExceptionPexpect:
                raise MPyg321WrongPlayerPathError(
                    """Invalid file path provided""")

        else:
            try:
                version_process = pexpect.spawn("mpg123 --version", encoding='utf-8')
                valid_player = "mpg123"
            except pexpect.exceptions.ExceptionPexpect:
                try:
                    version_process = pexpect.spawn("mpg321 --version", encoding='utf-8')
                    valid_player = "mpg321"
                except pexpect.exceptions.ExceptionPexpect:
                    raise MPyg321NoPlayerFoundError(
                        """No suitable player found""")

        suitable_versions = [
            re.compile(r"mpg123 ([0-9.]+)"),
            re.compile(r"mpg321 version ([0-9.]+)")
        ]
        index = version_process.expect(suitable_versions)
        try:
            self.player_name = suitable_versions[index]
            self.player_version = tuple(map(int, version_process.match.group(1).split('.')))  # e.g. (1, 30, 2)
        except IndexError:
            raise MPyg321NoPlayerFoundError("""No suitable player found""")
        return valid_player

    def set_player(self, player, audiodevice):
        """Sets the player"""
        player = self.set_version_and_get_player(player)
        args = "--remote" if self.player_name == "mpg123" else "-R test"
        args += " --audiodevice " + audiodevice if audiodevice else ""
        self.player = pexpect.spawn(str(player) + " " + args)
        self.player.delaybeforesend = None
        self.status = PlayerStatus.INSTANCIATED

    def process_output(self):
        """Parses the output"""
        while True:
            try:
                index = self.player.expect(mpg_codes)
            except pexpect.exceptions.EOF:
                return  # player has died; probably expected; just suppress exception
            action = mpg_outs[index]["action"]
            if action == MpgOutputAction.MUSIC_STOP:
                self.on_music_stop_int()
            elif action == MpgOutputAction.USER_PAUSE:
                self.on_user_pause_int()
            elif action == MpgOutputAction.USER_START_OR_RESUME:
                self.on_user_start_or_resume_int()
            elif action == MpgOutputAction.END_OF_SONG:
                self.on_end_of_song_int()
            elif action == MpgOutputAction.ERROR:
                self.on_error()
            elif action == MpgOutputAction.FRAME_UPDATE:
                self.on_frame_decoding_update_int(self.player.match.group(3))
            elif action == MpgOutputAction.INFORMATION:
                # print("Information:", self.player.match.group(0))
                pass
            # else:
            #     print(action)
            #     print(self.player.match)

    def play_song(self, path, loop=False):
        """Plays the song"""
        self.loop = loop
        self.set_song(path)
        self.play()

    def play(self):
        """Starts playing the song"""
        self.player.sendline("LOAD " + self.song_path)
        self.status = PlayerStatus.PLAYING

    def pause(self):
        """Pauses the player"""
        if self.status == PlayerStatus.PLAYING:
            self.player.sendline("PAUSE")
            self.status = PlayerStatus.PAUSED

    def resume(self):
        """Resume the player"""
        if self.status == PlayerStatus.PAUSED:
            self.player.sendline("PAUSE")
            self.on_user_resume()

    def stop(self):
        """Stops the player"""
        self.player.sendline("STOP")
        if self.player_name == "mpg321":
            self.status = PlayerStatus.STOPPED
        else:
            self.status = PlayerStatus.STOPPING

    def quit(self):
        """Quits the player"""
        self.player.sendline("QUIT")
        self.status = PlayerStatus.QUITTED

    def jump(self, pos):
        """Jump to position"""
        self.player.sendline("JUMP " + str(pos))

    def volume(self, percent):
        """Adjust player's volume"""
        if self.player_name == "mpg123":
            self.player.sendline("VOLUME {}".format(percent))
        if self.player_name == "mpg321":
            self.player.sendline("GAIN {}".format(percent))
        self.current_volume = percent

    def silence_mpyg_output(self):
        """Improves performance by silencing the mpg123 process frame output"""
        if self.player_name == "mpg123" and not self.performance_mode:
            self.player.sendline("SILENCE")

    def load_list(self, entry, filepath):
        """Load an entry in a list
        Parameters:
        entry (int): index of the song in the list - first is 0
        filepath: URL/Path to the list
        """
        if self.player_name == "mpg123":
            self.player.sendline("LOADLIST {} {}".format(entry, filepath))
            self.status = PlayerStatus.PLAYING

    def on_error(self):
        """Process errors encountered by the player"""
        output = self.player.readline().decode("utf-8")

        # Check error in list of errors
        for mpg_error in mpg_errors:
            if mpg_error["message"] in output:
                action = mpg_error["action"]
                if action == "generic_error":
                    raise MPyg321Error(output)
                if action == "file_error":
                    raise MPyg321FileError(output)
                if action == "command_error":
                    raise MPyg321CommandError(output)
                if action == "argument_error":
                    raise MPyg321ArgumentError(output)
                if action == "eq_error":
                    raise MPyg321EQError
                if action == "seek_error":
                    raise MPyg321SeekError

        # Some other error occurred
        raise MPyg321Error(output)

    def set_song(self, path):
        """song_path setter"""
        self.song_path = path

    def set_loop(self, loop):
        """"loop setter"""
        self.loop = loop

    # # # Internal Callbacks # # #
    def on_music_stop_int(self):
        """Internal callback when user stops the music"""
        if self.player_name == "mpg123":
            if self.status == PlayerStatus.STOPPING:
                self.status = PlayerStatus.STOPPED
                self.on_user_stop_int()
            else:
                # If not stopped by the user, it is the end of the song
                # the on_any_stop function is called inside on_end_of_song_int.
                # With mpg123 v1.30, there is now an explicit 'end of song'
                # notification, so this is only needed for older versions
                # of mpg123
                if (self.player_version[0] < 1) or (self.player_version[1] < 30):
                    self.on_end_of_song_int()
        else:
            self.on_user_stop_int()

    def on_user_stop_int(self):
        """Internal callback when the user stops the music."""
        self.on_any_stop()
        self.on_user_stop()

    def on_user_pause_int(self):
        """Internal callback when user pauses the music"""
        self.on_any_stop()
        self.on_user_pause()

    def on_user_start_or_resume_int(self):
        """Internal callback when user resumes the music"""
        self.status = PlayerStatus.PLAYING

    def on_end_of_song_int(self):
        """Internal callback when the song ends"""
        if(self.loop):
            self.play()
        else:
            # The music doesn't stop if it is looped
            self.on_any_stop()
        self.on_music_end()

    def on_frame_decoding_update_int(self, current_position):
        """Internal callback when there is a frame decoding update"""
        self.current_position = float(current_position)

    # # # Public Callbacks # # #
    def on_any_stop(self):
        """Callback when the music stops for any reason"""
        pass

    def on_user_pause(self):
        """Callback when user pauses the music"""
        pass

    def on_user_resume(self):
        """Callback when user resumes the music"""
        pass

    def on_user_stop(self):
        """Callback when user stops music"""
        pass

    def on_music_end(self):
        """Callback when music ends"""
        pass
