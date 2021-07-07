import dateutil.parser
import logging
import mutagen.mp3

from ..database.schema import Album, Track
from .common import find_coverart_file

logger = logging.getLogger(__name__)


def parse_ufid(ufid):
    return ufid.data.decode() if ufid else None


def scan_mp3(absolute_path):
    mp3 = mutagen.mp3.MP3(absolute_path)

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
            if '/' in m_of_n:
                m, n = m_of_n.split('/', 1)
                m = int(m)
                n = int(n)
                return m, n
            else:
                m = int(m_of_n)
                return m, None
        except ValueError:
            return None, None

    def get_tag_datetime_value(keys):
        val = get_tag_value(keys)
        if val:
            for datestr in val.text:
                logger.debug("Parsing datetime: %s", str(datestr))
                try:
                    return dateutil.parser.parse(datestr.text)
                except dateutil.parser._parser.ParserError:
                    pass  # try any remaining timestamps in the list
        return None

    def get_image_tag_value():
        val = mp3.tags.get('APIC:')
        return val.data if val else None

    artwork_path = find_coverart_file(absolute_path)
    artwork_blob = None if artwork_path else get_image_tag_value()

    track = Track(
        Filepath=str(absolute_path),
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
        ArtworkPath=artwork_path,
        ArtworkBlob=artwork_blob
    )

    albumref = Album(
        Title=get_first_tag_text_value(['TALB']),
        Artist=get_first_tag_text_value(['TPE2', 'TPE1']),
        VolumeCount=get_m_of_n(['TPOS'])[1],
        MusicBrainzAlbumId=get_first_tag_text_value(['TXXX:MusicBrainz Album Id']),
        MusicBrainzAlbumArtistId=get_first_tag_text_value(['TXXX:MusicBrainz Album Artist Id']),
    )

    return track, albumref
