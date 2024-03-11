class CurrentStatusStrings:
    """
    The collection of valid strings in current_status
    """
    STOPPED = 'stopped'
    PLAYING = 'playing'
    PAUSED = 'paused'


class PlayerInterface:
    """
    The methods common to both file-based and stream-based players
    """
    def __init__(self):
        self.current_status = CurrentStatusStrings.STOPPED
        self.current_volume = 100
        self.current_track_index = None  # 0-based
        self.state_change_callback = None
        # self.number_of_tracks = None  # must be available, but can be a property

    def set_state_change_callback(self, state_change_callback):
        self.state_change_callback = state_change_callback

    def send_now_playing_update(self):
        if self.state_change_callback:
            self.state_change_callback()

    def pause(self):
        raise NotImplementedError()

    def resume(self):
        raise NotImplementedError()

    def stop(self):
        raise NotImplementedError()

    def set_volume(self, volume):
        self.current_volume = volume
        raise NotImplementedError()
