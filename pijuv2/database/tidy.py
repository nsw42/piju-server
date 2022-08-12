import os.path

from .database import Database


def delete_missing_tracks(db: Database):
    to_delete = []
    for track in db.get_all_tracks():
        if not os.path.isfile(track.Filepath):
            to_delete.append(track.Id)
    for track_id in to_delete:
        db.delete_track(track_id)
