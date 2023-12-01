# pylint: disable=redefined-outer-name,unnecessary-dunder-call,unused-argument

from flask import Flask

import pytest

from pijuv2.scan.directory import set_cross_refs
from pijuv2.database.database import Database
from pijuv2.database.schema import Album, Artwork, Track

TEST_DB = 'test.db'


@pytest.fixture
def db_in_app_context(tmp_path):
    test_app = Flask(__name__)
    with test_app.app_context():
        Database.init_db(test_app, path=tmp_path / TEST_DB, create=True)
        yield Database()


def mk_albumref(artist, is_compilation, genres=None):
    return Album(Artist=artist, Title="Test Album Title", IsCompilation=is_compilation, Genres=genres if genres else [])


def mk_compilation_albumref():
    return mk_albumref("not used", True)


def mk_other_albumref():
    return mk_albumref("Bill and Ben", False)


def test_one_compilation_one_album(db_in_app_context):
    assert db_in_app_context.get_nr_albums() == 0

    db_in_app_context.ensure_album_exists(mk_compilation_albumref())

    assert db_in_app_context.get_nr_albums() == 1

    db_in_app_context.ensure_album_exists(mk_other_albumref())

    assert db_in_app_context.get_nr_albums() == 2

    db_in_app_context.ensure_album_exists(mk_compilation_albumref())

    assert db_in_app_context.get_nr_albums() == 2

    db_in_app_context.ensure_album_exists(mk_other_albumref())

    assert db_in_app_context.get_nr_albums() == 2


def test_one_album_one_compilation(db_in_app_context):
    assert db_in_app_context.get_nr_albums() == 0

    db_in_app_context.ensure_album_exists(mk_other_albumref())

    assert db_in_app_context.get_nr_albums() == 1

    db_in_app_context.ensure_album_exists(mk_compilation_albumref())

    assert db_in_app_context.get_nr_albums() == 2

    db_in_app_context.ensure_album_exists(mk_other_albumref())

    assert db_in_app_context.get_nr_albums() == 2

    db_in_app_context.ensure_album_exists(mk_compilation_albumref())

    assert db_in_app_context.get_nr_albums() == 2


def test_get_all_albums(db_in_app_context):
    assert db_in_app_context.get_all_albums() == []

    albumref = mk_other_albumref()
    db_in_app_context.ensure_album_exists(albumref)

    assert db_in_app_context.get_nr_albums() == 1

    album = db_in_app_context.get_all_albums()[0]

    assert album.Artist == albumref.Artist
    assert album.IsCompilation == albumref.IsCompilation


def test_get_all_tracks(db_in_app_context):
    assert db_in_app_context.get_all_tracks() == []

    trackref = Track(Title="Ringing Heaven's Doorbell")
    db_in_app_context.ensure_track_exists(trackref)

    assert db_in_app_context.get_nr_tracks() == 1

    track = db_in_app_context.get_all_tracks()[0]

    assert track.Title == trackref.Title


def test_get_album_by_id(db_in_app_context):
    # Prepare
    album1 = mk_other_albumref()
    db_in_app_context.ensure_album_exists(album1)
    album2 = mk_compilation_albumref()
    db_in_app_context.ensure_album_exists(album2)
    assert album1.Id != album2.Id
    assert album1.Artist != album2.Artist
    assert db_in_app_context.get_nr_albums() == 2

    # Act
    found = db_in_app_context.get_album_by_id(album1.Id)

    # Check
    assert found.Artist == album1.Artist


def test_get_genre_by_id(db_in_app_context):
    # Prepare
    genre_name = "Technocrat Jazz"
    genre = db_in_app_context.ensure_genre_exists(genre_name)

    db_in_app_context.ensure_album_exists(mk_albumref(artist="Da Vinci", is_compilation=False, genres=[genre]))
    db_in_app_context.ensure_album_exists(mk_other_albumref())

    assert db_in_app_context.get_nr_albums() == 2
    assert db_in_app_context.get_nr_genres() == 1

    # Act
    found = db_in_app_context.get_genre_by_id(genre.Id)

    # Check
    assert found.Id == genre.Id
    assert found.Name == genre_name
    assert len(found.Albums) == 1


def test_get_track_by_id(db_in_app_context):
    # Prepare
    trk1 = db_in_app_context.ensure_track_exists(Track(Title="Beware of the fish"))
    trk2 = db_in_app_context.ensure_track_exists(Track(Title="Something Something"))

    assert trk1.Id != trk2.Id
    assert db_in_app_context.get_nr_tracks() == 2

    # Act
    found = db_in_app_context.get_track_by_id(trk1.Id)

    # Check
    assert found.Title == "Beware of the fish"


def test_change_compilation_to_single_artist(db_in_app_context):
    # There used to be a bug that finding an album (eg as a compilation)
    # then re-scanning, and the album changing, meant that the first instance
    # of the album would stay around with no tracks in it.
    assert db_in_app_context.get_all_tracks() == []
    assert db_in_app_context.get_all_albums() == []

    # Simulate the outline of the logic from scan.directory
    # First pass: as a compilation
    trk1 = Track(Filepath='dummy.mp3',
                 Title='My Track',
                 Artist='Various Artists',
                 TrackNumber=1,
                 TrackCount=1)
    album1 = Album(Title='My Album',
                   Artist='Various Artists',
                   IsCompilation=True)
    set_cross_refs(db_in_app_context, trk1, album1, None)

    assert len(db_in_app_context.get_all_tracks()) == 1
    assert len(db_in_app_context.get_all_albums()) == 1

    assert trk1.Id is not None
    assert len(album1.Tracks) == 1

    # Second pass: as a single artist
    trk2 = Track(Id=trk1.Id,
                 Filepath='dummy.mp3',
                 Title='My Track',
                 Artist='Bill and Ben',
                 TrackNumber=1,
                 TrackCount=1)
    album2 = Album(Title='My Album',
                   Artist='Bill and Ben',
                   IsCompilation=False)
    set_cross_refs(db_in_app_context, trk2, album2, None)

    assert len(db_in_app_context.get_all_tracks()) == 1
    assert len(db_in_app_context.get_all_albums()) == 1


def test_delete_track_deletes_artwork(db_in_app_context):
    # Setup
    artref = Artwork(Path="/cover.jpg", Width=888, Height=777)
    artwork = db_in_app_context.ensure_artwork_exists(artref)
    trackref = Track(Title="Bohemian Rhapsody in Blue", Artwork=artwork.Id)
    track = db_in_app_context.ensure_track_exists(trackref)

    assert len(db_in_app_context.get_all_artworks()) == 1
    assert len(db_in_app_context.get_all_tracks()) == 1

    # Act
    db_in_app_context.delete_track(track.Id)

    # Check
    assert len(db_in_app_context.get_all_artworks()) == 0
    assert len(db_in_app_context.get_all_tracks()) == 0
