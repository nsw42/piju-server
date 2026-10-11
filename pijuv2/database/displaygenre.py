from enum import StrEnum
import re

DEFAULT_DISPLAY_GENRE_NAME = "Uncategorised"


class DisplayGenreIcon(StrEnum):
    "Abstract icon identifiers: it is up to the UI to map these to something it can draw"
    MUSIC = "music"
    RADIO = "radio"
    SPOKEN_WORD = "spoken_word"


class DisplayGenreViewStyle(StrEnum):
    LIST_OF_ALBUMS = "albums"
    LIST_OF_ARTISTS = "artists"


def normalize_genre_name(genre_name: str) -> str:
    """
    The form in which genre names are stored in the DisplayGenreMappings table:
    insensitive to case and to the punctuation that varies between taggers,
    so that "Post-Punk", "post punk" and "(Post Punk)" are all the same genre.
    """
    genre_name = genre_name.casefold()
    genre_name = re.sub(r'[/-]', ' ', genre_name)
    genre_name = re.sub(r'[()]', '', genre_name)
    genre_name = re.sub(r'  +', ' ', genre_name)
    return genre_name.strip()
