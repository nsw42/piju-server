import pathlib


def find_coverart_file(music_absolutepath: pathlib.Path):
    dir = music_absolutepath.parent
    for leaf in 'cover.jpg', 'cover.png':
        artwork_path = dir / leaf
        if artwork_path.is_file():
            return str(artwork_path)
    return None
