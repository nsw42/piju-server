# pylint: disable=redefined-outer-name,unnecessary-dunder-call,unused-argument
from unittest.mock import MagicMock, patch

import pytest

from pijuv2.backend.appfactory import create_app
from pijuv2.database.database import DatabaseAccess


@pytest.fixture()
def test_app(tmp_path):
    app = create_app(tmp_path / 'test.db', create_db=True)
    app.config.update({
        'TESTING': True
    })
    yield app


@pytest.fixture()
def client(test_app):
    yield test_app.test_client()


@pytest.fixture()
def real_db(test_app):
    with test_app.app_context():
        yield DatabaseAccess


@pytest.fixture()
def mock_dbaccess():
    with patch('pijuv2.backend.routes.DatabaseAccess') as mock_dbaccess:
        yield mock_dbaccess


@pytest.fixture()
def mock_album6(mock_dbaccess, mock_track12):
    mock_album = MagicMock()
    mock_album.Id = 6
    mock_album.Artist = 'Various Artists'
    mock_album.Title = 'The Best of Celtic Folk Music'
    mock_album.ReleaseYear = 2020
    mock_album.IsCompilation = True
    mock_album.VolumeCount = 30
    mock_album.Tracks = [mock_track12]
    mock_album.Genres = []
    mock_dbaccess().__enter__().get_album_by_id.return_value = mock_album


@pytest.fixture()
def mock_track12(mock_dbaccess):
    mock_track = MagicMock()
    mock_track.Id = 12
    mock_track.Artist = 'Motörhead'
    mock_track.Title = 'Ace of Spades'
    mock_track.Genre = 'Easy Listening'
    mock_track.VolumeNumber = 1
    mock_track.TrackNumber = 1
    mock_track.TrackCount = 2
    mock_track.Filepath = '/beware/of/the/leopard.mp3'
    mock_track.Album = mock_track.ArtworkPath = mock_track.ArtworkBlob = None
    mock_dbaccess().__enter__().get_track_by_id.return_value = mock_track
    return mock_track


def test_get_album_default_info_level(client, mock_album6):
    response = client.get('/albums/6')
    assert response.status_code == 200
    assert response.json['link'] == '/albums/6'
    assert response.json['artist'] == 'Various Artists'
    assert response.json['title'] == 'The Best of Celtic Folk Music'
    assert response.json['tracks'] == ['/tracks/12']


def test_get_album_all_info(client, mock_album6):
    response = client.get('/albums/6?tracks=all')
    assert response.status_code == 200
    assert response.json['tracks'][0]['artist'] == 'Motörhead'
    assert response.json['tracks'][0]['title'] == 'Ace of Spades'


def test_get_status(client, real_db):
    response = client.get('/')
    assert response.status_code == 200
    assert response.json['PlayerStatus'] == 'stopped'


def test_get_track(client, mock_track12):
    response = client.get('/tracks/12')
    assert response.status_code == 200
    assert response.json['link'] == '/tracks/12'
    assert response.json['artist'] == 'Motörhead'
    assert response.json['title'] == 'Ace of Spades'
    assert response.json['artwork'] is None
    assert response.json['artworkinfo'] is None


def test_get_track_with_artwork(client, mock_track12):
    mock_track12.ArtworkPath = '/over/the/rainbow.jpg'
    response = client.get('/tracks/12')
    assert response.status_code == 200
    assert response.json['artwork'] == '/artwork/12'
    assert response.json['artworkinfo'] == '/artworkinfo/12'
