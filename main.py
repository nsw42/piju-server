import pathlib

from sqlalchemy import select

from database import Database
from schema import Album
# from scan_mp3 import scan_mp3
from scan_m4a import scan_m4a

basedir = pathlib.Path('/') / 'Users' / 'Shared' / 'iTunes Media' / 'Music'


def main():
    db = Database()

    album_refs = set()

    # for path in basedir.rglob('*.mp3'):
    #     track = scan_mp3(path)
    #     print(track)
    for path in basedir.rglob('*.m4a'):
        print(path)
        track, albumref = scan_m4a(path)  # These are pure object models - no ids or cross references yet
        # fill in ids and cross-references
        db.track(track)  # updates track.Id
        track.Album = db.album(albumref)  # also updates albumref.Id
        print("  Album %s (%s==%s): Track %s" % (albumref.Title, track.Album, albumref.Id, track.Title))
        albumref.Tracks.append(track)

        album_refs.add((albumref.Artist, albumref.Title))
        # print(track.Id)
        # print(albumref)

    # dump all albums
    print("Albums:")
    albums = db.session.execute(select(Album).order_by(Album.Artist, Album.Title))
    for album in albums.scalars().all():
        print("Artist: '%s', Title: '%s', Id: '%s'" % (album.Artist, album.Title, album.Id))
        print("  Tracks:")
        for track in sorted(album.Tracks, key=lambda t: -1 if (t.TrackNumber is None) else t.TrackNumber):
            print("    %s: %s (%s)" % (track.TrackNumber, track.Title, track.Filepath))

    # and all tracks


if __name__ == '__main__':
    main()
