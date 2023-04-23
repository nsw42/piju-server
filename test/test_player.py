from unittest.mock import patch

from pijuv2.database.schema import Track
import pijuv2.player.player as player


def test_play_from_real_queue_index_empty_queue():
    mp = player.MusicPlayer()
    mp.play_from_real_queue_index(0)
    assert mp.current_status == 'stopped'
    assert mp.current_track_id is None


@patch('pijuv2.player.player.os.path.isfile')
def test_play_from_real_queue_index__file_does_not_exist(mock_isfile):
    # Arrange
    mock_isfile.return_value = False
    track = Track()
    track.Filepath = 'nosuchfile.mp3'

    # Act
    mp = player.MusicPlayer(queue=[track])
    mp.play_from_real_queue_index(0)

    # Assert
    assert mp.current_status == 'stopped'
    assert mp.current_track_id is None


@patch('pijuv2.player.player.os.path.isfile')
@patch('pijuv2.player.player.MP3MusicPlayer')
def test_play_from_real_queue_index__file_exists(mock_mp3player, mock_isfile):
    # Arrange
    mock_isfile.return_value = True
    track = Track()
    track.Id = 12345
    track.Filepath = 'fileexists.mp3'

    # Act
    mp = player.MusicPlayer(queue=[track])
    mp.play_from_real_queue_index(0)

    # Assert
    assert mp.current_status == 'playing'
    assert mp.current_track_id == 12345
    mp.current_player.play_song.assert_called_once_with('fileexists.mp3')


@patch('pijuv2.player.player.os.path.isfile')
@patch('pijuv2.player.player.MP3MusicPlayer')
def test_play_from_real_queue_index__two_files_in_queue(mock_mp3player, mock_isfile):
    # Arrange
    mock_isfile.side_effect = [False, True]
    t1 = Track()
    t1.Id = 123
    t1.Filepath = 'doesnotexist.mp3'
    t2 = Track()
    t2.Id = 456
    t2.Filepath = 'exists.mp3'

    # Act
    mp = player.MusicPlayer(queue=[t1, t2])
    mp.play_from_real_queue_index(0)

    # Assert
    assert mp.current_status == 'playing'
    assert mp.current_track_id == 456
    mp.current_player.play_song.assert_called_once_with('exists.mp3')
