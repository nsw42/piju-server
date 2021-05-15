import pathlib

from sqlalchemy import select

from database import Database
from schema import Album, Track
from scan_mp3 import scan_mp3
from scan_m4a import scan_m4a

basedir = pathlib.Path('/') / 'Users' / 'Shared' / 'iTunes Media' / 'Music'


def main():
    db = Database()

    def set_cross_refs(track: Track, albumref: Album):
        db.track(track)  # updates track.Id
        track.Album = db.album(albumref)  # also updates albumref.Id and adds track to albumref.Tracks

    for path in basedir.rglob('*.mp3'):
        track, albumref = scan_mp3(path)
        set_cross_refs(track, albumref)

    for path in basedir.rglob('*.m4a'):
        track, albumref = scan_m4a(path)
        set_cross_refs(track, albumref)

    # dump all albums
    print("Albums:")
    albums = db.session.execute(select(Album).order_by(Album.Artist, Album.Title))
    for album in albums.scalars().all():
        print("Artist: '%s', Title: '%s', Id: %s" % (album.Artist, album.Title, album.Id))
        print("  Tracks:")
        for track in sorted(album.Tracks, key=lambda t: -1 if (t.TrackNumber is None) else t.TrackNumber):
            print("    %s: %s (%s)" % (track.TrackNumber, track.Title, track.Filepath))
    print("\n\n")

    # and all tracks
    print("Tracks:")
    tracks = db.session.execute(select(Track).order_by(Track.Artist, Track.Album, Track.TrackNumber))
    for track in tracks.scalars().all():
        print("Id: %s, Artist: '%s', Album id: %s, Track number: %s, Track title: '%s', Genre: '%s'" % (
            track.Id, track.Artist, track.Album, track.TrackNumber, track.Title, track.Genre))
    print("\n\n")


if __name__ == '__main__':
    main()
