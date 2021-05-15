import logging

import dateutil.parser
import mutagen.mp4

# from model import Track
from schema import Album, Track

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def scan_m4a(absolute_path):
    mp4 = mutagen.mp4.MP4(absolute_path)

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
        return dateutil.parser.isoparse(val) if val else None

    track = Track(
        Filepath=str(absolute_path),
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
        MusicBrainzAlbumId=None,
        MusicBrainzAlbumArtistId=None,
    )

    return track, albumref
