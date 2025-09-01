import logging
import os.path

from .database import Database


def delete_missing_tracks(db: Database):
    to_delete = []
    start_id = 0
    query_size = 100
    while (tracks := db.get_all_tracks_paged(start_id, query_size)) is not None:
        logging.debug(f"delete_missing_tracks: offset={start_id}")
        for track in tracks:
            if not os.path.isfile(track.Filepath):
                logging.debug(f"{track.Filepath} ({track.Id}) not found")
                to_delete.append(track.Id)
        start_id += query_size
    for track_id in to_delete:
        logging.debug(f"Deleting track {track_id}")
        db.delete_track(track_id)


def delete_albums_without_tracks(db: Database):
    to_delete = db.get_albums_without_tracks()
    # There are optimisations possible, taking advantage of pushing the query into the db and avoiding the iteration,
    # but this is quick enough
    for album in to_delete:
        logging.debug(f'Deleting album {album.Id}')
        db.delete_album(album.Id)


def delete_artwork_without_tracks(db: Database):
    to_delete = db.get_artwork_without_tracks()
    for artwork in to_delete:
        logging.debug(f'Deleting artwork {artwork.Id}')
        db.delete_artwork(artwork.Id)


def delete_empty_genres(db: Database):
    to_delete = db.get_empty_genres()
    for genre in to_delete:
        logging.debug(f'Deleting genre {genre.Id}')
        db.delete_genre(genre.Id)
