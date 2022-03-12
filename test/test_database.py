import os

from pijuv2.database.database import Database
from pijuv2.database.schema import Album

TEST_DB = 'test.db'

def mk_albumref(artist, is_compilation):
    return Album(Artist=artist, Title="Test Album Title", IsCompilation=is_compilation)


def mk_compilation_albumref():
    return mk_albumref("not used", True)


def mk_other_albumref():
    return mk_albumref("Bill and Ben", False)


def test_one_compilation_one_album(tmp_path):
    db = Database(path=tmp_path / TEST_DB)

    assert db.get_nr_albums() == 0

    db.ensure_album_exists(mk_compilation_albumref())

    assert db.get_nr_albums() == 1

    db.ensure_album_exists(mk_other_albumref())

    assert db.get_nr_albums() == 2

    db.ensure_album_exists(mk_compilation_albumref())

    assert db.get_nr_albums() == 2

    db.ensure_album_exists(mk_other_albumref())

    assert db.get_nr_albums() == 2


def test_one_album_one_compilation(tmp_path):
    db = Database(path=tmp_path / TEST_DB)

    assert db.get_nr_albums() == 0

    album1 = db.ensure_album_exists(mk_other_albumref())

    assert db.get_nr_albums() == 1

    album2 = db.ensure_album_exists(mk_compilation_albumref())

    assert db.get_nr_albums() == 2

    album3 = db.ensure_album_exists(mk_other_albumref())

    assert db.get_nr_albums() == 2

    album4 = db.ensure_album_exists(mk_compilation_albumref())

    assert db.get_nr_albums() == 2

