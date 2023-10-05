from collections import namedtuple
from datetime import datetime
import io
import logging
import pathlib
from typing import Optional

from PIL import Image, UnidentifiedImageError

ArtworkSize = namedtuple('ArtworkSize', 'width height')


def parse_datetime_str(datestr: str):
    # Previously tried dateutil.parser, but if given '1994' it would return
    # a datetime equal to datetime.date.today(), with the year changed to 1994.
    # step 1: split yyyy-mm-dd from hh:mm:ss
    if 'T' in datestr:
        yyyymmdd, hhmmss = datestr.split('T', 1)
    elif ' ' in datestr:
        yyyymmdd, hhmmss = datestr.split(' ', 1)
    else:
        yyyymmdd, hhmmss = datestr, ''
    # step 2: parse yyyy-mm-dd
    if '-' in yyyymmdd:
        yyyymmdd = yyyymmdd.split('-')
    else:
        yyyymmdd = [yyyymmdd]
    while len(yyyymmdd) < 3:
        yyyymmdd.append('')
    if len(yyyymmdd) > 3:
        raise ValueError(f'malformed date: {datestr}')
    if not all(field == '' or field.isdigit() for field in yyyymmdd):
        raise ValueError(f'malformed date: {datestr}')
    yyyymmdd = [1 if (field == '') else int(field) for field in yyyymmdd]
    # step 3: parse hh:mm:ss[TZ]
    if hhmmss and not any(c.isdigit() for c in hhmmss):
        raise ValueError(f'malformed date: {datestr}')
    if '+' in hhmmss:
        hhmmss = hhmmss[:hhmmss.index('+')]
    if '-' in hhmmss:
        hhmmss = hhmmss[:hhmmss.index('-')]
    while hhmmss and not hhmmss[-1].isdigit():
        hhmmss = hhmmss[:-1]
    if ':' in hhmmss:
        hhmmss = hhmmss.split(':')
    else:
        hhmmss = [hhmmss]
    while len(hhmmss) < 3:
        hhmmss.append('')
    if len(hhmmss) > 3:
        raise ValueError(f'malformed date: {datestr}')
    if not all(field == '' or field.isdigit() for field in hhmmss):
        raise ValueError(f'malformed date: {datestr}')
    hhmmss = [0 if (field == '') else int(field) for field in hhmmss]
    # recombine and construct a datetime
    dtvalues = yyyymmdd + hhmmss
    return datetime(*dtvalues)


def find_coverart_file(music_absolutepath: pathlib.Path):
    directory = music_absolutepath.parent
    for leaf in 'cover.jpg', 'cover.png':
        artwork_path = directory / leaf
        if artwork_path.is_file():
            return str(artwork_path)
    return None


def get_artwork_size(artwork_path: pathlib.Path, artwork_blob: bytes) -> Optional[ArtworkSize]:
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


if __name__ == '__main__':
    import doctest
    doctest.testmod()
