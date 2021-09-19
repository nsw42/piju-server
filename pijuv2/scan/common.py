from collections import namedtuple
import io
import pathlib
from typing import Optional

from PIL import Image

ArtworkSize = namedtuple('ArtworkSize', 'width height')


def find_coverart_file(music_absolutepath: pathlib.Path):
    dir = music_absolutepath.parent
    for leaf in 'cover.jpg', 'cover.png':
        artwork_path = dir / leaf
        if artwork_path.is_file():
            return str(artwork_path)
    return None


def get_artwork_size(artwork_path: pathlib.Path, artwork_blob: bytes) -> Optional[ArtworkSize]:
    if artwork_path:
        im = Image.open(artwork_path)
    elif artwork_blob:
        im = Image.open(io.BytesIO(artwork_blob))
    else:
        return None

    return ArtworkSize(im.width, im.height)
