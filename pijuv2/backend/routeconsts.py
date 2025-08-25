# This collection of route constants allows us to avoid using Flask's url_for.
# url_for requires SERVER_NAME to be set, which then results in requests
# being rejected if they access the app via another hostname.
# At the simplest level, this means that setting SERVER_NAME=myserver
# prevents requests to http://localhost:5000/ from working.

import re
from urllib.parse import quote

from flask import has_request_context

from .appwrapper import current_piju_app


class RouteConstants:
    GET_ALBUM = '/albums/<albumid>'
    GET_ARTIST = '/artists/<path:artist>'  # Pretend artist is a full-path, so we correctly handle bands like 'AC/DC'
    GET_ARTWORK = '/artwork/<artworkid>'
    GET_ARTWORK_INFO = '/artworkinfo/<artworkid>'
    GET_GENRE = '/genres/<genreid>'
    GET_ONE_PLAYLIST = '/playlists/<playlistid>'
    GET_ONE_RADIO_STATION = '/radio/<stationid>'
    GET_TRACK = '/tracks/<trackid>'

    @staticmethod
    def url_for(route, **kwargs) -> str:
        for kwarg, val in kwargs.items():
            if not isinstance(val, str):
                val = str(val)
            route = re.sub(r'<([^>:]*:)?' + kwarg + '>', val, route)

        return quote(route) if has_request_context() else current_piju_app.server_address + quote(route)

    @staticmethod
    def url_for_get_album(albumid):
        return RouteConstants.url_for(RouteConstants.GET_ALBUM, albumid=albumid)

    @staticmethod
    def url_for_get_artist(artist):
        return RouteConstants.url_for(RouteConstants.GET_ARTIST, artist=artist)

    @staticmethod
    def url_for_get_artwork(artworkid):
        return RouteConstants.url_for(RouteConstants.GET_ARTWORK, artworkid=artworkid)

    @staticmethod
    def url_for_get_artwork_info(artworkid):
        return RouteConstants.url_for(RouteConstants.GET_ARTWORK_INFO, artworkid=artworkid)

    @staticmethod
    def url_for_get_genre(genreid):
        return RouteConstants.url_for(RouteConstants.GET_GENRE, genreid=genreid)

    @staticmethod
    def url_for_get_one_playlist(playlistid):
        return RouteConstants.url_for(RouteConstants.GET_ONE_PLAYLIST, playlistid=playlistid)

    @staticmethod
    def url_for_get_one_radio_station(stationid):
        return RouteConstants.url_for(RouteConstants.GET_ONE_RADIO_STATION, stationid=stationid)

    @staticmethod
    def url_for_get_track(trackid):
        return RouteConstants.url_for(RouteConstants.GET_TRACK, trackid=trackid)
