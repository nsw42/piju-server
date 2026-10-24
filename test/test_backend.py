# pylint: disable=redefined-outer-name,unnecessary-dunder-call,unused-argument
from unittest.mock import MagicMock, patch

import pytest

from pijuv2.backend.appfactory import create_app
from pijuv2.backend.workrequests import WorkRequests
from pijuv2.database.database import Database, DatabaseAccess, NotFoundException
from pijuv2.database.schema import Album, DisplayGenre, Track


@pytest.fixture()
def test_app(tmp_path):
    app = create_app(config_file=None, db_path=tmp_path / 'test.db', create_db=True)
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
    mock_track.Album = mock_track.Artwork = None
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


def test_get_album_display_genres(client, mock_dbaccess, mock_album6):
    mock_album = mock_dbaccess().__enter__().get_album_by_id.return_value
    mock_album.Genres = [MagicMock(Id=8, DisplayGenreId=3),
                         MagicMock(Id=9, DisplayGenreId=5),
                         MagicMock(Id=10, DisplayGenreId=3)]
    response = client.get('/albums/6')
    assert response.status_code == 200
    assert response.json['genres'] == ['/genres/8', '/genres/9', '/genres/10']
    assert response.json['display_genres'] == ['/display_genre/3', '/display_genre/5']


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
    mock_track12.Artwork = 6
    response = client.get('/tracks/12')
    assert response.status_code == 200
    assert response.json['artwork'] == '/artwork/6'
    assert response.json['artworkinfo'] == '/artworkinfo/6'


@pytest.fixture()
def mock_display_genre3(mock_dbaccess):
    mock_genre = MagicMock()
    mock_genre.Id = 8
    mock_display_genre = MagicMock()
    mock_display_genre.Id = 3
    mock_display_genre.Name = 'Rock & Pop'
    mock_display_genre.Icon = 'music'
    mock_display_genre.ViewStyle = 'albums'
    mock_display_genre.Genres = [mock_genre]
    mock_albums = []
    for album_id in (21, 22):
        mock_album = MagicMock()
        mock_album.Id = album_id
        mock_albums.append(mock_album)
    mock_db = mock_dbaccess().__enter__()
    mock_db.get_all_display_genres.return_value = [mock_display_genre]
    mock_db.get_display_genre_album_counts.return_value = {3: 45}
    mock_db.get_display_genre_by_id.return_value = mock_display_genre
    mock_db.get_display_genre_albums.return_value = (mock_albums, 45)
    mock_db.get_display_genre_playlists.return_value = []
    return mock_db


def test_get_all_display_genres(client, mock_display_genre3):
    response = client.get('/display_genre/')
    assert response.status_code == 200
    assert response.json == [{
        'link': '/display_genre/3',
        'id': 3,
        'name': 'Rock & Pop',
        'icon': 'music',
        'view_style': 'albums',
        'album_count': 45,
    }]


def test_get_all_display_genres_empty(client, mock_display_genre3):
    mock_display_genre3.get_display_genre_album_counts.return_value = {}
    response = client.get('/display_genre/')
    assert response.status_code == 200
    assert response.json[0]['album_count'] == 0


def test_get_display_genre_default_paging(client, mock_display_genre3):
    response = client.get('/display_genre/3')
    assert response.status_code == 200
    mock_display_genre3.get_display_genre_albums.assert_called_once_with(3, 0, 20)
    assert response.json['link'] == '/display_genre/3'
    assert response.json['name'] == 'Rock & Pop'
    assert response.json['genres'] == ['/genres/8']
    assert response.json['albums'] == ['/albums/21', '/albums/22']
    assert response.json['playlists'] == []
    assert response.json['pagination'] == {
        'offset': 0,
        'limit': 20,
        'total': 45,
        'next': '/display_genre/3?offset=20&limit=20',
        'prev': None,
    }


def test_get_display_genre_middle_page(client, mock_display_genre3):
    response = client.get('/display_genre/3?albums=none&offset=15&limit=10')
    assert response.status_code == 200
    mock_display_genre3.get_display_genre_albums.assert_called_once_with(3, 15, 10)
    assert 'albums' not in response.json
    pagination = response.json['pagination']
    assert pagination['next'] == '/display_genre/3?albums=none&offset=25&limit=10'
    assert pagination['prev'] == '/display_genre/3?albums=none&offset=5&limit=10'


def test_get_display_genre_last_page(client, mock_display_genre3):
    response = client.get('/display_genre/3?offset=40')
    assert response.status_code == 200
    assert response.json['pagination']['next'] is None
    assert response.json['pagination']['prev'] == '/display_genre/3?offset=20&limit=20'


def test_get_display_genre_limit_is_capped(client, mock_display_genre3):
    response = client.get('/display_genre/3?limit=5000')
    assert response.status_code == 200
    mock_display_genre3.get_display_genre_albums.assert_called_once_with(3, 0, 100)
    assert response.json['pagination']['limit'] == 100


@pytest.mark.parametrize('query', ['offset=-1', 'offset=abc', 'limit=0', 'limit=-5', 'limit=lots'])
def test_get_display_genre_bad_paging(client, mock_display_genre3, query):
    response = client.get('/display_genre/3?' + query)
    assert response.status_code == 400


def test_get_display_genre_unknown_id(client, mock_display_genre3):
    mock_display_genre3.get_display_genre_by_id.side_effect = NotFoundException()
    response = client.get('/display_genre/99')
    assert response.status_code == 404


def test_display_genres_end_to_end(client, real_db):
    with real_db() as db:
        genre = db.ensure_genre_exists('Rock')
        genre_id = genre.Id
        default_id = genre.DisplayGenreId
        album = db.ensure_album_exists(Album(Artist='Motörhead', Title='Ace of Spades', IsCompilation=False,
                                             Genres=[genre]))
        album_id = album.Id
        other = DisplayGenre(Name='Rock & Pop', Icon='music', ViewStyle='albums', SortOrder=1)
        Database.db.session.add(other)
        Database.db.session.commit()
        other_id = other.Id

    response = client.get('/display_genre/')
    assert [(dg['name'], dg['album_count']) for dg in response.json] == [('Uncategorised', 1), ('Rock & Pop', 0)]

    response = client.get(f'/display_genre/{default_id}?albums=all')
    assert response.status_code == 200
    assert [album['title'] for album in response.json['albums']] == ['Ace of Spades']
    assert response.json['pagination']['total'] == 1
    assert response.json['pagination']['next'] is None

    response = client.get(f'/genres/{genre_id}')
    assert response.json['display_genre'] == f'/display_genre/{default_id}'
    assert client.get(f'/albums/{album_id}').json['display_genres'] == [f'/display_genre/{default_id}']

    # Move the genre into the other display genre
    response = client.put(f'/genres/{genre_id}', json={'display_genre': f'/display_genre/{other_id}'})
    assert response.status_code == 200
    assert response.json['display_genre'] == f'/display_genre/{other_id}'
    assert client.get(f'/display_genre/{default_id}').json['pagination']['total'] == 0
    response = client.get(f'/display_genre/{other_id}')
    assert response.json['genres'] == [f'/genres/{genre_id}']
    assert response.json['pagination']['total'] == 1
    assert client.get(f'/albums/{album_id}').json['display_genres'] == [f'/display_genre/{other_id}']

    response = client.get('/display_genre/')
    assert [(dg['name'], dg['album_count']) for dg in response.json] == [('Uncategorised', 0), ('Rock & Pop', 1)]

    assert client.put(f'/genres/{genre_id}', json={'display_genre': 9999}).status_code == 400
    assert client.put(f'/genres/{genre_id}', json={'display_genre': 'rock'}).status_code == 400
    assert client.put('/genres/9999', json={'display_genre': other_id}).status_code == 404


def test_scan_clears_cached_responses(test_app, client, real_db):
    with real_db() as db:
        genre = db.ensure_genre_exists('Rock')
        album = db.ensure_album_exists(Album(Artist='Motörhead', Title='Ace of Spades', IsCompilation=False,
                                             Genres=[genre]))
        album_id = album.Id
        other = DisplayGenre(Name='Rock & Pop', Icon='music', ViewStyle='albums', SortOrder=1)
        Database.db.session.add(other)
        Database.db.session.commit()
        other_id = other.Id
    assert client.get(f'/albums/{album_id}').json['display_genres'] != [f'/display_genre/{other_id}']

    def fake_scan_directory(_dir_to_scan, db):
        # Stands in for a scan that changes the album's genres
        db.get_album_by_id(album_id).Genres[0].DisplayGenreId = other_id

    with patch('pijuv2.backend.workthread.scan_directory', side_effect=fake_scan_directory):
        test_app.worker.process_request((WorkRequests.SCAN_DIRECTORY, '/music'))

    assert client.get(f'/albums/{album_id}').json['display_genres'] == [f'/display_genre/{other_id}']


def test_edit_unknown_playlist(client, real_db):
    with real_db() as db:
        track = db.ensure_track_exists(Track(Filepath='/beware/of/the/leopard.mp3', Title='Ace of Spades'))
        track_id = track.Id
    response = client.put('/playlists/9999', json={'title': 'Loud', 'tracks': [f'/tracks/{track_id}']})
    assert response.status_code == 404


def test_edit_unknown_radio_station(client, real_db):
    response = client.put('/radio/9999', json={'name': 'Radio Nowhere', 'url': 'http://example.com/stream'})
    assert response.status_code == 404


@pytest.mark.parametrize('route', ['/artwork/9999', '/artworkinfo/9999'])
def test_get_unknown_artwork(client, real_db, route):
    response = client.get(route)
    assert response.status_code == 404
    assert 'Unknown artwork id' in response.get_data(as_text=True)
