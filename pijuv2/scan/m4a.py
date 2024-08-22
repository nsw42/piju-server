import logging
from pathlib import Path
from typing import Optional, Tuple

import mutagen.mp4

from ..database.schema import Album, Artwork, Track
from .common import find_coverart_file, get_artwork_size, make_artwork_ref, parse_datetime_str, normalize_filepath

logger = logging.getLogger(__name__)


def scan_m4a(absolute_path: Path) -> Tuple[Track, Album, Optional[Artwork]]:
    logging.debug(f"Scanning M4A: {absolute_path}")
    mp4 = mutagen.mp4.MP4(absolute_path)
    if not mp4.tags:
        logging.warning(f"No M4A tags found in file '{absolute_path}'")
        return None, None, None

    def get_tag_value(keys):
        for key in keys:
            val = mp4.tags.get(key) if mp4.tags else None
            if val:
                return val[0]
        logger.debug(f"{absolute_path}: Found no value for {keys}")
        return None

    def get_tag_text_value(keys):
        val = get_tag_value(keys)
        return val

    def get_m_of_n(keys):
        val = get_tag_value(keys)
        if not val:
            return None, None
        return val

    def get_tag_datetime_value(keys):
        val = get_tag_value(keys)
        logger.debug("Parsing datetime: %s", val)
        return parse_datetime_str(val) if val else None

    def get_tag_image_value(keys):
        val = get_tag_value(keys)
        return val  # no post-processing seems to be necessary

    artwork_path = find_coverart_file(absolute_path)
    artwork_blob = None if artwork_path else get_tag_image_value(['covr'])
    artwork_size = get_artwork_size(artwork_path, artwork_blob)

    track = Track(
        Filepath=normalize_filepath(absolute_path),
        Title=get_tag_text_value(['\xa9nam']),
        Duration=int(1000 * mp4.info.length),
        Composer=get_tag_text_value(['\xa9wrt']),
        Artist=get_tag_text_value(['\xa9ART']),
        Genre=get_tag_text_value(['\xa9gen']),
        VolumeNumber=get_m_of_n(['disk'])[0],
        TrackCount=get_m_of_n(['trkn'])[1],
        TrackNumber=get_m_of_n(['trkn'])[0],
        ReleaseDate=get_tag_datetime_value(['\xa9day']),
        MusicBrainzTrackId=None,
        MusicBrainzArtistId=None,
    )

    albumref = Album(
        Title=get_tag_text_value(['\xa9alb']),
        Artist=get_tag_text_value(['aART', '\xa9ART']),
        VolumeCount=get_m_of_n(['disk'])[1],
        IsCompilation=False,  # TODO
        MusicBrainzAlbumId=None,
        MusicBrainzAlbumArtistId=None,
        ReleaseYear=track.ReleaseDate.year if track.ReleaseDate else None
    )

    artworkref = make_artwork_ref(artwork_path, artwork_blob, artwork_size)

    return track, albumref, artworkref
