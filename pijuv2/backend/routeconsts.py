# This collection of route constants allows us to avoid using url_for.
# url_for requires SERVER_NAME to be set, which then results in requests
# being rejected if they access the app via another hostname.
# At the simplest level, this means that setting SERVER_NAME=myserver
# prevents requests to http://localhost:5000/ from working.

import re
from urllib.parse import quote

from flask import current_app, has_request_context


class RouteConstants:
    GET_ALBUM = '/albums/<albumid>'
    GET_ARTIST = '/artists/<path:artist>'
    GET_ARTWORK = '/artwork/<artworkid>'
    GET_ARTWORK_INFO = '/artworkinfo/<artworkid>'
    GET_GENRE = '/genres/<genreid>'
    GET_ONE_PLAYLIST = '/playlists/<playlistid>'
    GET_ONE_RADIO_STATION = '/radio/<stationid>'
    GET_TRACK = '/tracks/<trackid>'


def url_for(route, **kwargs) -> str:
    for kwarg, val in kwargs.items():
        if not isinstance(val, str):
            val = str(val)
        route = re.sub(r'<([^>:]*:)?' + kwarg + '>', val, route)

    return quote(route) if has_request_context() else current_app.server_address + quote(route)
