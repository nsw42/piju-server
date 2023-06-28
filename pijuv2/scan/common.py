from collections import namedtuple
from datetime import datetime
import io
import pathlib
from typing import Optional

from PIL import Image

ArtworkSize = namedtuple('ArtworkSize', 'width height')


def parse_datetime_str(datestr: str):
    """
    >>> parse_datetime_str('1994')
    datetime.datetime(1994, 1, 1, 0, 0)
    >>> # be tolerant of malformed date strings
    >>> parse_datetime_str('2021-09')
    datetime.datetime(2021, 9, 1, 0, 0)
    >>> parse_datetime_str('1997-05-12')
    datetime.datetime(1997, 5, 12, 0, 0)
    >>> # allow times to be specified, too
    >>> parse_datetime_str('2001-12-31T23:29:59Z')
    datetime.datetime(2001, 12, 31, 23, 29, 59)
    >>> parse_datetime_str('2001-12-31 23:29:59Z')
    datetime.datetime(2001, 12, 31, 23, 29, 59)
    >>> # tolerate missing timezone indicator
    >>> parse_datetime_str('2001-12-31T23:29:59')
    datetime.datetime(2001, 12, 31, 23, 29, 59)
    >>> # allow for other timezones - although don't actually honour the indicated timezone
    >>> parse_datetime_str('2001-12-31T23:29:59PDT')
    datetime.datetime(2001, 12, 31, 23, 29, 59)
    >>> parse_datetime_str('2015-07-15T16:54:33+0100')
    datetime.datetime(2015, 7, 15, 16, 54, 33)
    >>> parse_datetime_str('2016-08-29T21:32:06-0700')
    datetime.datetime(2016, 8, 29, 21, 32, 6)
    >>> # tolerance only goes so far
    >>> parse_datetime_str('Some point in the 21st Century')
    Traceback (most recent call last):
        ...
    ValueError: malformed date: Some point in the 21st Century
    """
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
    if artwork_path:
        img = Image.open(artwork_path)
    elif artwork_blob:
        img = Image.open(io.BytesIO(artwork_blob))
    else:
        return None

    return ArtworkSize(img.width, img.height)


if __name__ == '__main__':
    import doctest
    doctest.testmod()
