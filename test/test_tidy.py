from pijuv2.database.database import Database
from pijuv2.database.schema import Album, Track
from pijuv2.database.tidy import delete_missing_tracks, delete_albums_without_tracks

TEST_DB = 'test.db'


def mk_existing_track(tmp_path):
    existing_path = tmp_path / 'dummy.mp3'
    open(existing_path, 'w').write('dummy')
    return Track(Filepath=str(existing_path), Title='Dummy track')


def mk_non_existing_track():
    return Track(Filepath='/no/such/path', Title='Nonexistent path')


def test_delete_missing_tracks(tmp_path):
    db = Database(path=tmp_path / TEST_DB)

    assert db.get_nr_tracks() == 0

    existing_track = mk_existing_track(tmp_path)
    db.ensure_track_exists(existing_track)
    db.ensure_track_exists(mk_non_existing_track())

    assert db.get_nr_tracks() == 2

    delete_missing_tracks(db)

    assert db.get_nr_tracks() == 1

    t = db.get_all_tracks()[0]
    assert t.Id == existing_track.Id
    assert t.Filepath == existing_track.Filepath


def test_delete_albums_without_tracks(tmp_path):
    db = Database(path=tmp_path / TEST_DB)

    a1 = db.ensure_album_exists(Album(Title="Album With A Track"))
    t = Track(Title="Dummy Track", Album=a1.Id)
    db.ensure_track_exists(t)

    db.ensure_album_exists(Album(Title="Album Without Tracks"))

    assert db.get_nr_tracks() == 1
    assert db.get_nr_albums() == 2

    delete_albums_without_tracks(db)

    assert db.get_nr_tracks() == 1
    assert db.get_nr_albums() == 1

    a = db.get_all_albums()[0]
    assert a.Id == a1.Id
    assert a.Title == "Album With A Track"