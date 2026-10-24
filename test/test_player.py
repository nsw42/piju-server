from unittest.mock import patch

import pytest

from pijuv2.database.schema import Track
import pijuv2.player.fileplayer as fileplayer
from pijuv2.player.fileplayer import ControlAction


@pytest.fixture(autouse=True)
def mock_control_thread():
    # FilePlayer hands playback off to a background thread, which would otherwise race
    # with the assertions and outlive the test (launching real players after the mocks are removed)
    with patch('pijuv2.player.fileplayer.FilePlayerControl') as mock_control:
        yield mock_control


def test_play_from_real_queue_index_empty_queue():
    player = fileplayer.FilePlayer()
    player.play_from_real_queue_index(0)
    assert player.current_status == 'stopped'
    assert player.current_track is None


@patch('pijuv2.player.fileplayer.os.path.isfile')
def test_play_from_real_queue_index__file_does_not_exist(mock_isfile):
    # Arrange
    mock_isfile.return_value = False
    track = Track()
    track.Filepath = 'nosuchfile.mp3'

    # Act
    player = fileplayer.FilePlayer(queue=[track])
    player.play_from_real_queue_index(0)

    # Assert
    assert player.current_status == 'stopped'
    assert player.current_track is None


@patch('pijuv2.player.fileplayer.os.path.isfile')
def test_set_queue_starts_playing__file_exists(mock_isfile, mock_control_thread):
    # Arrange
    mock_isfile.return_value = True
    track = Track()
    track.Id = 12345
    track.Filepath = 'fileexists.mp3'

    # Act
    player = fileplayer.FilePlayer()
    player.set_queue([track], "queue")

    # Assert
    assert player.current_status == 'playing'
    assert player.current_track.trackid == 12345
    mock_control_thread().queue_action.assert_called_with(ControlAction.PLAY, 'fileexists.mp3', True)


@patch('pijuv2.player.fileplayer.os.path.isfile')
def test_set_queue_starts_playing__two_files_in_queue(mock_isfile, mock_control_thread):
    # Arrange
    mock_isfile.side_effect = [False, True]
    trk1 = Track()
    trk1.Id = 123
    trk1.Filepath = 'doesnotexist.mp3'
    trk2 = Track()
    trk2.Id = 456
    trk2.Filepath = 'exists.mp3'

    # Act
    player = fileplayer.FilePlayer()
    player.set_queue([trk1, trk2], "queue")

    # Assert
    assert player.current_status == 'playing'
    assert player.current_track.trackid == 456
    mock_control_thread().queue_action.assert_called_with(ControlAction.PLAY, 'exists.mp3', True)


@patch('pijuv2.player.fileplayer.os.path.isfile')
def test_play_from_real_queue_index__off_by_one(mock_isfile, mock_control_thread):
    # Arrange
    mock_isfile.return_value = True
    trk1 = Track()
    trk1.Id = 123
    trk1.Filepath = '1.mp3'
    trk2 = Track()
    trk2.Id = 234
    trk2.Filepath = '2.mp3'

    # Act
    player = fileplayer.FilePlayer(queue=[trk1, trk2])
    player.play_from_real_queue_index(0, 234)

    # Assert
    assert player.current_status == 'playing'
    assert player.current_track_index == 1
    assert player.current_track.trackid == 234
    mock_control_thread().queue_action.assert_called_with(ControlAction.PLAY, '2.mp3', True)


@patch('pijuv2.player.fileplayer.os.path.isfile')
def test_play_from_real_queue_index__off_by_one_the_other_way(mock_isfile, mock_control_thread):
    # Arrange
    mock_isfile.return_value = True
    trk1 = Track()
    trk1.Id = 123
    trk1.Filepath = '1.mp3'
    trk2 = Track()
    trk2.Id = 234
    trk2.Filepath = '2.mp3'

    # Act
    player = fileplayer.FilePlayer(queue=[trk1, trk2])
    player.play_from_real_queue_index(1, 123)

    # Assert
    assert player.current_status == 'playing'
    assert player.current_track_index == 0
    assert player.current_track.trackid == 123
    mock_control_thread().queue_action.assert_called_with(ControlAction.PLAY, '1.mp3', True)
