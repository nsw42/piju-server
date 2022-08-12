from pijuv2.database.database import Database
from pijuv2.database.schema import Album, Track
from pijuv2.scan.directory import set_cross_refs

TEST_DB = 'test.db'


def test_change_track_genre(tmp_path):
    db = Database(path=tmp_path / TEST_DB)

    assert db.get_nr_albums() == db.get_nr_tracks() == 0

    # setup: track in one genre; that track in an album

    t1 = Track(Title="Track 1", Genre="Rock")
    albumref = Album(Title="Album")
    set_cross_refs(db, t1, albumref)

    # verify setup is as expected

    assert db.get_nr_albums() == 1
    assert db.get_nr_tracks() == 1
    album = db.get_all_albums()[0]
    track = db.get_all_tracks()[0]
    assert album.Tracks == [track]
    assert len(album.Genres) == 1
    genre1id = album.Genres[0].Id
    assert genre1id == track.Genre

    # test: update the track to a new genre

    t2 = Track(Id=t1.Id, Title="Still Track 1", Genre="Punk")
    set_cross_refs(db, t2, albumref)

    # verify updates were as expected

    assert db.get_nr_albums() == 1
    assert db.get_nr_tracks() == 1

    track = db.get_all_tracks()[0]
    genre2id = track.Genre
    assert genre1id != genre2id

    album = db.get_all_albums()[0]
    assert len(album.Genres) == 1
    assert album.Genres[0].Id == genre2id

    assert len(db.get_all_genres()) == 2  # don't [yet] expect empty genres to be automatically deleted
    genre1 = db.get_genre_by_id(genre1id)
    assert len(genre1.Albums) == 0
    genre2 = db.get_genre_by_id(genre2id)
    assert len(genre2.Albums) == 1
