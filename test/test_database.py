# pylint: disable=redefined-outer-name,unnecessary-dunder-call,unused-argument

from flask import Flask

import pytest

from pijuv2.scan.directory import set_cross_refs
from pijuv2.database.database import Database, NotFoundException
from pijuv2.database.displaygenre import normalize_genre_name
from pijuv2.database.schema import Album, Artwork, DisplayGenre, DisplayGenreMapping, Track

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


def test_get_unknown_artist_alias_gives_empty_list(db_in_app_context):
    # Setup
    # Act
    res = db_in_app_context.get_artist_aliases('Mononym')

    # Check
    assert res == []


def test_add_artist_alias(db_in_app_context):
    # Setup
    # Act
    db_in_app_context.add_artist_alias('Sea Power', 'British Sea Power')

    # Check
    res = db_in_app_context.get_artist_aliases('Sea Power')
    assert res == ['British Sea Power']


def test_multiple_artist_aliases(db_in_app_context):
    # Setup
    db_in_app_context.add_artist_alias('Bill', 'Bob')

    # Act
    db_in_app_context.add_artist_alias('Bill', 'Ben')

    # Check
    res = db_in_app_context.get_artist_aliases('Bill')
    assert set(res) == {'Bob', 'Ben'}


def test_delete_artist_aliases(db_in_app_context):
    # Setup
    db_in_app_context.add_artist_alias('Al', 'Weird Al')
    db_in_app_context.add_artist_alias('Al', '"Weird" Al')

    # Act
    db_in_app_context.delete_artist_aliases('Al')

    # Check
    res = db_in_app_context.get_artist_aliases('Al')
    assert res == []


def test_delete_one_artist_alias(db_in_app_context):
    # Setup
    tmbg = 'They Might Be Giants'
    db_in_app_context.add_artist_alias(tmbg, 'TMBG')
    db_in_app_context.add_artist_alias(tmbg, 'They')

    # Act
    db_in_app_context.remove_one_artist_alias(tmbg, 'They')

    # Check
    res = db_in_app_context.get_artist_aliases(tmbg)
    assert res == ['TMBG']


def mk_display_genre(db, name, genre_names, sort_order=0):
    display_genre = DisplayGenre(Name=name, Icon='music', ViewStyle='albums', SortOrder=sort_order)
    Database.db.session.add(display_genre)
    Database.db.session.commit()
    for genre_name in genre_names:
        Database.db.session.add(DisplayGenreMapping(GenreName=normalize_genre_name(genre_name),
                                                    DisplayGenreId=display_genre.Id))
    Database.db.session.commit()
    return display_genre


def mk_album_in_genres(db, artist, title, genres, year=None, is_compilation=False):
    return db.ensure_album_exists(Album(Artist=artist, Title=title, ReleaseYear=year,
                                        IsCompilation=is_compilation, Genres=genres))


def test_new_genre_uses_display_genre_mapping(db_in_app_context):
    rock = mk_display_genre(db_in_app_context, "Rock & Pop", ["Post Punk", "Rock"])

    for genre_name in ("Rock", "post-punk", "(Post/Punk)"):
        genre = db_in_app_context.ensure_genre_exists(genre_name)
        assert genre.DisplayGenreId == rock.Id


def test_new_unmapped_genre_uses_default_display_genre(db_in_app_context):
    rock = mk_display_genre(db_in_app_context, "Rock & Pop", ["Rock"])

    genre1 = db_in_app_context.ensure_genre_exists("Technocrat Jazz")
    genre2 = db_in_app_context.ensure_genre_exists("Bureaucrat Blues")

    assert genre1.DisplayGenreId != rock.Id
    assert genre1.DisplayGenreId == genre2.DisplayGenreId
    default = db_in_app_context.get_display_genre_by_id(genre1.DisplayGenreId)
    assert default.IsDefault
    assert default.Name == "Uncategorised"
    # the default display genre is created once, after the existing ones
    assert [dg.Id for dg in db_in_app_context.get_all_display_genres()] == [rock.Id, default.Id]


def test_get_all_display_genres_is_in_sort_order(db_in_app_context):
    mk_display_genre(db_in_app_context, "Second", [], sort_order=2)
    mk_display_genre(db_in_app_context, "First", [], sort_order=1)

    assert [dg.Name for dg in db_in_app_context.get_all_display_genres()] == ["First", "Second"]


def test_get_display_genre_albums_order_and_paging(db_in_app_context):
    rock = mk_display_genre(db_in_app_context, "Rock & Pop", ["Rock", "Pop"])
    mk_display_genre(db_in_app_context, "Classical", ["Classical"], sort_order=1)
    genre_rock = db_in_app_context.ensure_genre_exists("Rock")
    genre_pop = db_in_app_context.ensure_genre_exists("Pop")
    genre_classical = db_in_app_context.ensure_genre_exists("Classical")
    mk_album_in_genres(db_in_app_context, "zebra", "Stripes", [genre_rock], year=2001)
    mk_album_in_genres(db_in_app_context, "Aardvark", "Later", [genre_pop], year=2005)
    # in two genres of the same display genre: must only be reported once
    mk_album_in_genres(db_in_app_context, "Aardvark", "Earlier", [genre_rock, genre_pop], year=1999)
    mk_album_in_genres(db_in_app_context, "not used", "Compilation", [genre_pop], is_compilation=True)
    mk_album_in_genres(db_in_app_context, "Bach", "Fugues", [genre_classical])

    albums, total = db_in_app_context.get_display_genre_albums(rock.Id, offset=0, limit=20)
    assert total == 4
    assert [album.Title for album in albums] == ["Earlier", "Later", "Stripes", "Compilation"]

    albums, total = db_in_app_context.get_display_genre_albums(rock.Id, offset=1, limit=2)
    assert total == 4
    assert [album.Title for album in albums] == ["Later", "Stripes"]

    albums, total = db_in_app_context.get_display_genre_albums(rock.Id, offset=4, limit=2)
    assert total == 4
    assert albums == []


def test_get_display_genre_albums_order_ignores_quotes(db_in_app_context):
    comedy = mk_display_genre(db_in_app_context, "Comedy", ["Comedy"])
    genre_comedy = db_in_app_context.ensure_genre_exists("Comedy")
    mk_album_in_genres(db_in_app_context, "Yorgi Yorgesson", "Yorgi", [genre_comedy])
    mk_album_in_genres(db_in_app_context, '"Weird Al" Yankovic', "Poodle Hat", [genre_comedy])
    mk_album_in_genres(db_in_app_context, "Bob Newhart", "Something Like That", [genre_comedy], year=2001)
    mk_album_in_genres(db_in_app_context, "Bob Newhart", "\u2018Something Like This\u2019", [genre_comedy], year=2001)
    mk_album_in_genres(db_in_app_context, "Bob Newhart", "'Something Like Those'", [genre_comedy], year=2001)
    mk_album_in_genres(db_in_app_context, "Billy Connolly", "Classic Connolly", [genre_comedy])

    albums, _ = db_in_app_context.get_display_genre_albums(comedy.Id, offset=0, limit=20)
    assert [(album.Artist, album.Title) for album in albums] == [
        ("Billy Connolly", "Classic Connolly"),
        ("Bob Newhart", "Something Like That"),
        ("Bob Newhart", "\u2018Something Like This\u2019"),
        ("Bob Newhart", "'Something Like Those'"),
        ('"Weird Al" Yankovic', "Poodle Hat"),
        ("Yorgi Yorgesson", "Yorgi"),
    ]


def test_set_genre_display_genre_is_remembered(db_in_app_context):
    rock = mk_display_genre(db_in_app_context, "Rock & Pop", ["Rock"])
    jazz = mk_display_genre(db_in_app_context, "Jazz", [], sort_order=1)
    genre = db_in_app_context.ensure_genre_exists("Jazz-Rock")
    assert genre.DisplayGenreId not in (rock.Id, jazz.Id)

    db_in_app_context.set_genre_display_genre(genre.Id, jazz.Id)
    assert db_in_app_context.get_genre_by_id(genre.Id).DisplayGenreId == jazz.Id
    assert [g.Name for g in db_in_app_context.get_display_genre_by_id(jazz.Id).Genres] == ["Jazz-Rock"]

    # The mapping survives the genre being deleted (eg by a tidy) and scanned again
    db_in_app_context.delete_genre(genre.Id)
    assert db_in_app_context.ensure_genre_exists("Jazz Rock").DisplayGenreId == jazz.Id

    # ... and can be changed again
    genre = db_in_app_context.ensure_genre_exists("Jazz Rock")
    db_in_app_context.set_genre_display_genre(genre.Id, rock.Id)
    assert db_in_app_context.ensure_genre_exists("jazz/rock").DisplayGenreId == rock.Id


def test_set_genre_display_genre_unknown_ids(db_in_app_context):
    genre = db_in_app_context.ensure_genre_exists("Rock")
    with pytest.raises(NotFoundException):
        db_in_app_context.set_genre_display_genre(genre.Id, 12345)
    with pytest.raises(NotFoundException):
        db_in_app_context.set_genre_display_genre(12345, genre.DisplayGenreId)
