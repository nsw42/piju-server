import os.path

from .database import Database


def delete_missing_tracks(db: Database):
    to_delete = []
    for track in db.get_all_tracks():
        if not os.path.isfile(track.Filepath):
            to_delete.append(track.Id)
    for track_id in to_delete:
        db.delete_track(track_id)


def delete_albums_without_tracks(db: Database):
    to_delete = db.get_albums_without_tracks()
    # There are optimisations possible, taking advantage of pushing the query into the db and avoiding the iteration,
    # but this is quick enough
    for album in to_delete:
        db.delete_album(album.Id)