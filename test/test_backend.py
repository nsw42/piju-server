# pylint: disable=redefined-outer-name,unnecessary-dunder-call
from unittest.mock import MagicMock, patch

import pytest

from pijuv2.backend.appfactory import create_app
from pijuv2.database.database import Database, DatabaseAccess


@pytest.fixture()
def client(tmp_path):
    Database.DEFAULT_URI = Database.SQLITE_PREFIX + str(tmp_path / 'test.db')
    app = create_app()
    app.config.update({
        'TESTING': True
    })
    with DatabaseAccess(create=True) as db:
        print(db.get_nr_albums())
    return app.test_client()


@pytest.fixture()
def client_with_mock_db():
    with patch('pijuv2.backend.routes.DatabaseAccess') as mock_dbaccess:
        mock_track = MagicMock()
        mock_track.Id = 12
        mock_track.Artist = 'Motörhead'
        mock_track.Title = 'Ace of Spades'
        mock_track.Genre = 'Easy Listening'
        mock_track.VolumeNumber = 1
        mock_track.TrackNumber = 1
        mock_track.TrackCount = 2
        mock_track.Filepath = '/beware/of/the/leopard.mp3'
        mock_track.Album = mock_track.ArtworkPath = mock_track.ArtworkBlock = None
        mock_dbaccess().__enter__().get_track_by_id.return_value = mock_track
        app = create_app()
        app.config.update({
            'TESTING': True
        })
        yield app.test_client()


def test_get_status(client):
    response = client.get('/')
    assert response.status_code == 200
    assert response.json['PlayerStatus'] == 'stopped'


def test_get_track(client_with_mock_db):
    response = client_with_mock_db.get('/tracks/12')
    assert response.status_code == 200
    assert response.json['link'] == '/tracks/12'
    assert response.json['artist'] == 'Motörhead'
    assert response.json['title'] == 'Ace of Spades'
