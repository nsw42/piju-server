import logging
from pathlib import Path
from typing import Tuple, Optional

import mutagen.mp3

from ..database.schema import Album, Artwork, Track
from .common import find_coverart_file, get_artwork_size, make_artwork_ref, parse_datetime_str, normalize_filepath

logger = logging.getLogger(__name__)


def parse_ufid(ufid):
    return ufid.data.decode() if ufid else None


def scan_mp3(absolute_path: Path) -> Tuple[Track, Artwork, Optional[Album]]:
    logging.debug(f"Scanning MP3: {absolute_path}")
    mp3 = mutagen.mp3.MP3(absolute_path)
    if not mp3.tags:
        logging.warning(f"{absolute_path}: no MP3 tags found. Skipping file.")
        return None, None

    def get_tag_value(keys):
        for key in keys:
            val = mp3.tags.get(key)
            if val:
                return val
        logger.debug(f"{absolute_path}: Found no value for {keys}")
        return None

    def get_tag_text_value(keys):
        val = get_tag_value(keys)
        return val.text if val else None

    def get_first_tag_text_value(keys):
        val = get_tag_text_value(keys)
        return val[0] if val else None

    def get_m_of_n(keys):
        val = get_tag_value(keys)
        if not val:
            return None, None
        m_of_n = val.text[0]
        try:
            # pylint: disable=C0103  # ignore 'm' and 'n' as bad variable names
            if '/' in m_of_n:
                m, n = m_of_n.split('/', 1)
                m = int(m)
                n = int(n)
                return m, n
            else:
                m = int(m_of_n)
                return m, None
            # pylint: enable=C0103
        except ValueError:
            return None, None

    def get_tag_datetime_value(keys):
        val = get_tag_value(keys)
        if val:
            for datestr in val.text:
                datestr = datestr.text
                logger.debug("Parsing datetime: %s", datestr)
                try:
                    return parse_datetime_str(datestr)
                except ValueError:
                    pass  # try any remaining timestamps in the list
        return None

    def get_image_tag_value():
        val = mp3.tags.get('APIC:')
        return val.data if val else None

    artwork_path = find_coverart_file(absolute_path)
    artwork_blob = None if artwork_path else get_image_tag_value()
    artwork_size = get_artwork_size(artwork_path, artwork_blob)

    track = Track(
        Filepath=normalize_filepath(absolute_path),
        Title=get_first_tag_text_value(['TIT2']),
        Duration=int(1000 * mp3.info.length),
        Composer=get_first_tag_text_value(['TCOM']),
        Artist=get_first_tag_text_value(['TPE1', 'TPE2']),
        Genre=get_first_tag_text_value(['TCON']),
        VolumeNumber=get_m_of_n(['TPOS'])[0],
        TrackCount=get_m_of_n(['TRCK'])[1],
        TrackNumber=get_m_of_n(['TRCK'])[0],
        ReleaseDate=get_tag_datetime_value(['TDRL', 'TDOR', 'TYER', 'TDRC']),
        MusicBrainzTrackId=(parse_ufid(mp3.tags.get('UFID:http://musicbrainz.org'))
                            or get_first_tag_text_value(['TXXX:MusicBrainz Release Track Id'])),
        MusicBrainzArtistId=get_first_tag_text_value(['TXXX:MusicBrainz Artist Id']),
    )

    if not track.Title:
        track.Title = absolute_path.with_suffix('').name
        logging.warning(f"{absolute_path}: No track title found. Using {track.Title}.")

    albumref = Album(
        Title=get_first_tag_text_value(['TALB']),
        Artist=get_first_tag_text_value(['TPE2', 'TPE1']),
        VolumeCount=get_m_of_n(['TPOS'])[1],
        IsCompilation=True if (get_first_tag_text_value(['TCMP']) == '1') else False,
        MusicBrainzAlbumId=get_first_tag_text_value(['TXXX:MusicBrainz Album Id']),
        MusicBrainzAlbumArtistId=get_first_tag_text_value(['TXXX:MusicBrainz Album Artist Id']),
        ReleaseYear=track.ReleaseDate.year if track.ReleaseDate else None
    )

    artworkref = make_artwork_ref(artwork_path, artwork_blob, artwork_size)

    return track, albumref, artworkref
