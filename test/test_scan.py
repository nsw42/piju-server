from flask import Flask

from pijuv2.database.database import Database, DatabaseAccess
from pijuv2.database.schema import Album, Track
from pijuv2.scan.directory import set_cross_refs

TEST_DB = 'test.db'


def test_change_track_genre(tmp_path):
    # setup: track in one genre; that track in an album
    test_app = Flask(__name__)
    with test_app.app_context():
        Database.init_db(test_app, path=tmp_path / TEST_DB, create=True)
        with DatabaseAccess() as db:
            assert db.get_nr_albums() == db.get_nr_tracks() == 0

            trk1 = Track(Title="Track 1", Genre="Rock")
            albumref = Album(Title="Album")
            set_cross_refs(db, trk1, albumref, None)
            t1id = trk1.Id

        # verify setup is as expected
        with DatabaseAccess() as db:
            assert db.get_nr_albums() == 1
            assert db.get_nr_tracks() == 1
            album = db.get_all_albums()[0]
            track = db.get_all_tracks()[0]
            assert album.Tracks == [track]
            assert len(album.Genres) == 1
            genre1id = album.Genres[0].Id
            assert genre1id == track.Genre

        # test: update the track to a new genre
        with DatabaseAccess() as db:
            trk2 = Track(Id=t1id, Title="Still Track 1", Genre="Punk")
            albumref = Album(Title="Album")
            set_cross_refs(db, trk2, albumref, None)

        # verify updates were as expected
        with DatabaseAccess() as db:
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
