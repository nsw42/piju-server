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

    def pause(self):
        raise NotImplementedError()

    def resume(self):
        raise NotImplementedError()

    def stop(self):
        raise NotImplementedError()

    def set_volume(self, volume):
        self.current_volume = volume
        raise NotImplementedError()
