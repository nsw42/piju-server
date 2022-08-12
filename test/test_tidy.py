from pijuv2.database.database import Database
from pijuv2.database.schema import Track
from pijuv2.database.tidy import delete_missing_tracks

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
