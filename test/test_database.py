from pijuv2.scan.directory import set_cross_refs
from pijuv2.database.database import Database
from pijuv2.database.schema import Album, Track

TEST_DB = 'test.db'


def mk_albumref(artist, is_compilation, genres=[]):
    return Album(Artist=artist, Title="Test Album Title", IsCompilation=is_compilation, Genres=genres)


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

    db.ensure_album_exists(mk_other_albumref())

    assert db.get_nr_albums() == 1

    db.ensure_album_exists(mk_compilation_albumref())

    assert db.get_nr_albums() == 2

    db.ensure_album_exists(mk_other_albumref())

    assert db.get_nr_albums() == 2

    db.ensure_album_exists(mk_compilation_albumref())

    assert db.get_nr_albums() == 2


def test_get_all_albums(tmp_path):
    db = Database(path=tmp_path / TEST_DB)

    assert db.get_all_albums() == []

    albumref = mk_other_albumref()
    db.ensure_album_exists(albumref)

    assert db.get_nr_albums() == 1

    album = db.get_all_albums()[0]

    assert album.Artist == albumref.Artist
    assert album.IsCompilation == albumref.IsCompilation


def test_get_all_tracks(tmp_path):
    db = Database(path=tmp_path / TEST_DB)

    assert db.get_all_tracks() == []

    trackref = Track(Title="Ringing Heaven's Doorbell")
    db.ensure_track_exists(trackref)

    assert db.get_nr_tracks() == 1

    track = db.get_all_tracks()[0]

    assert track.Title == trackref.Title


def test_get_album_by_id(tmp_path):
    # Prepare
    db = Database(path=tmp_path / TEST_DB)
    a1 = mk_other_albumref()
    db.ensure_album_exists(a1)
    a2 = mk_compilation_albumref()
    db.ensure_album_exists(a2)
    assert a1.Id != a2.Id
    assert a1.Artist != a2.Artist
    assert db.get_nr_albums() == 2

    # Act
    found = db.get_album_by_id(a1.Id)

    # Check
    assert found.Artist == a1.Artist


def test_get_genre_by_id(tmp_path):
    # Prepare
    db = Database(path=tmp_path / TEST_DB)

    genre_name = "Technocrat Jazz"
    genre = db.ensure_genre_exists(genre_name)

    db.ensure_album_exists(mk_albumref(artist="Da Vinci", is_compilation=False, genres=[genre]))
    db.ensure_album_exists(mk_other_albumref())

    assert db.get_nr_albums() == 2
    assert db.get_nr_genres() == 1

    # Act
    found = db.get_genre_by_id(genre.Id)

    # Check
    assert found.Id == genre.Id
    assert found.Name == genre_name
    assert len(found.Albums) == 1


def test_change_compilation_to_single_artist(tmp_path):
    # There used to be a bug that finding an album (eg as a compilation)
    # then re-scanning, and the album changing, meant that the first instance
    # of the album would stay around with no tracks in it.
    db = Database(path=tmp_path / TEST_DB)

    assert db.get_all_tracks() == []
    assert db.get_all_albums() == []

    # Simulate the outline of the logic from scan.directory
    # First pass: as a compilation
    t1 = Track(Filepath='dummy.mp3',
               Title='My Track',
               Artist='Various Artists',
               TrackNumber=1,
               TrackCount=1)
    a1 = Album(Title='My Album',
               Artist='Various Artists',
               IsCompilation=True)
    set_cross_refs(db, t1, a1)

    assert len(db.get_all_tracks()) == 1
    assert len(db.get_all_albums()) == 1

    assert t1.Id is not None
    assert len(a1.Tracks) == 1

    # Second pass: as a single artist
    t2 = Track(Id=t1.Id,
               Filepath='dummy.mp3',
               Title='My Track',
               Artist='Bill and Ben',
               TrackNumber=1,
               TrackCount=1)
    a2 = Album(Title='My Album',
               Artist='Bill and Ben',
               IsCompilation=False)
    set_cross_refs(db, t2, a2)

    assert len(db.get_all_tracks()) == 1
    assert len(db.get_all_albums()) == 1
