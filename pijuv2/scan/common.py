from collections import namedtuple
from datetime import datetime
import io
import logging
import pathlib
from typing import Tuple
import unicodedata

from PIL import Image, UnidentifiedImageError

from ..database.schema import Artwork

ArtworkSize = namedtuple('ArtworkSize', 'width height')


def parse_datetime_str__split_yyyymmdd_hhmmss(datestr: str) -> Tuple[str, str]:
    "Given a datestring, split it into its yyyymmdd and hhmmss constituents"
    if 'T' in datestr:
        yyyymmdd, hhmmss = datestr.split('T', 1)
    elif ' ' in datestr:
        yyyymmdd, hhmmss = datestr.split(' ', 1)
    else:
        yyyymmdd, hhmmss = datestr, ''
    return yyyymmdd, hhmmss


def parse_datetime_str__yyyymmdd(datestr: str, yyyymmdd: str) -> list[int]:
    "Given the yyyymmdd from a datestring, split it into a list of ints"
    if '-' in yyyymmdd:
        yyyymmdd_l_str = yyyymmdd.split('-')
    else:
        yyyymmdd_l_str = [yyyymmdd]
    while len(yyyymmdd_l_str) < 3:
        yyyymmdd_l_str.append('')
    if len(yyyymmdd_l_str) > 3:
        raise ValueError(f'malformed date: {datestr}')
    if not all(field == '' or field.isdigit() for field in yyyymmdd_l_str):
        raise ValueError(f'malformed date: {datestr}')
    yyyymmdd_l_int = [1 if (field == '') else int(field) for field in yyyymmdd_l_str]
    return yyyymmdd_l_int


def parse_datetime_str__hhmmss(datestr: str, hhmmss: str) -> list[int]:
    "Given the hhmmss from a datestring, split it into a list of ints"
    if hhmmss and not any(c.isdigit() for c in hhmmss):
        raise ValueError(f'malformed date: {datestr}')
    if '+' in hhmmss:
        hhmmss = hhmmss[:hhmmss.index('+')]
    if '-' in hhmmss:
        hhmmss = hhmmss[:hhmmss.index('-')]
    while hhmmss and not hhmmss[-1].isdigit():
        hhmmss = hhmmss[:-1]
    if ':' in hhmmss:
        hhmmss_l_str = hhmmss.split(':')
    else:
        hhmmss_l_str = [hhmmss]
    while len(hhmmss_l_str) < 3:
        hhmmss_l_str.append('')
    if len(hhmmss_l_str) > 3:
        raise ValueError(f'malformed date: {datestr}')
    if not all(field == '' or field.isdigit() for field in hhmmss_l_str):
        raise ValueError(f'malformed date: {datestr}')
    hhmmss_l_int = [0 if (field == '') else int(field) for field in hhmmss_l_str]
    return hhmmss_l_int


def parse_datetime_str(datestr: str):
    # Previously tried dateutil.parser, but if given '1994' it would return
    # a datetime equal to datetime.date.today(), with the year changed to 1994.
    '''
    Note that repr(datetime) doesn't include the seconds if they're zero
    >>> parse_datetime_str('2014-06-09T07:00:00Z')
    datetime.datetime(2014, 6, 9, 7, 0)
    '''

    yyyymmdd, hhmmss = parse_datetime_str__split_yyyymmdd_hhmmss(datestr)  # split yyyy-mm-dd from hh:mm:ss

    yyyymmdd_l_int = parse_datetime_str__yyyymmdd(datestr, yyyymmdd)  # parse yyyy-mm-dd

    hhmmss_l_int = parse_datetime_str__hhmmss(datestr, hhmmss)  # parse hh:mm:ss[TZ]

    # recombine and construct a datetime
    dtvalues = yyyymmdd_l_int + hhmmss_l_int
    return datetime(*dtvalues)  # type: ignore


def find_coverart_file(music_absolutepath: pathlib.Path) -> pathlib.Path | None:
    directory = music_absolutepath.parent
    for leaf in 'cover.jpg', 'cover.png', 'cover.webp':
        artwork_path = directory / leaf
        if artwork_path.is_file():
            return artwork_path
    return None


def get_artwork_size(artwork_path: pathlib.Path | None,
                     artwork_blob: bytes | None) -> ArtworkSize | None:
    try:
        if artwork_path:
            img = Image.open(artwork_path)
        elif artwork_blob:
            img = Image.open(io.BytesIO(artwork_blob))
        else:
            return None
    except UnidentifiedImageError as exc:
        logging.error(f"Error scanning {artwork_path}: {exc}")
        return None

    return ArtworkSize(img.width, img.height)


def make_artwork_ref(artwork_path: str | pathlib.Path | None,
                     artwork_blob: bytes | None,
                     artwork_size: ArtworkSize | None):
    if artwork_path or artwork_blob:
        return Artwork(
            Path=str(artwork_path) if artwork_path else None,
            Blob=artwork_blob,
            Width=artwork_size.width if artwork_size else None,
            Height=artwork_size.height if artwork_size else None,
        )
    else:
        return None


def normalize_filepath(path: pathlib.Path | str) -> str:
    if not isinstance(path, str):
        path = str(path)

    return unicodedata.normalize('NFC', path)
