from collections import defaultdict
import gzip
from http import HTTPStatus
import json
import mimetypes
import os.path
from pathlib import Path
import time
from typing import Any, Dict, List, NamedTuple
from urllib.parse import urlencode

from flask import Blueprint, jsonify, make_response, request, Response
from flask_sock import Sock
from werkzeug.exceptions import BadRequest, BadRequestKeyError, Conflict, InternalServerError, NotFound

from ..database.database import DatabaseAccess, NotFoundException
from ..database.schema import Album, Playlist, Track
from .appwrapper import current_piju_app
from .downloadinfo import DownloadInfo, DownloadInfoDatabaseSingleton
from .deserialize import build_playlist_from_api_data, build_radio_station_from_api_data
from .deserialize import extract_display_genre_id_from_api_data, extract_id, parse_bool
from .nowplaying import get_current_status
from .playerctrl import add_track_to_queue, queue_downloaded_files, select_player, update_player_play_radio_station
from .playerctrl import update_player_play_from_local, update_player_play_from_radio, update_player_play_from_youtube
from .playerctrl import update_player_streaming_prevnext
from .queuesession import get_browser_queue, get_browser_queue_by_session_id, session_id_for_request
from .queuesession import set_browser_queue, QUEUE_SESSION_HEADER
from .routeconsts import RouteConstants
from .serialize import json_display_genre, json_display_genre_contents
from .serialize import json_genre, json_playlist, json_track_or_file
from .serialize import clear_cached_responses, InformationLevel
from .serialize import json_album, json_radio_station, json_track
from .workrequests import WorkRequests

routes = Blueprint('routes', __name__, url_prefix='')
sock = Sock()

ERR_MSG_UNKNOWN_ALBUM_ID = 'Unknown album id'
ERR_MSG_UNKNOWN_ARTWORK_ID = 'Unknown artwork id'
ERR_MSG_UNKNOWN_DISPLAY_GENRE_ID = 'Unknown display genre id'
ERR_MSG_UNKNOWN_GENRE_ID = 'Unknown genre id'
ERR_MSG_UNKNOWN_TRACK_ID = 'Unknown track id'
ERR_MSG_UNKNOWN_PLAYLIST_ID = 'Unknown playlist id'
ERR_MSG_UNKNOWN_RADIO_ID = 'Unknown radio station id'
ERR_MSG_NO_QUEUE_WHEN_STREAMING = "Queue operations not permitted when playing streaming content"

ARG_NAME_MODE = 'mode'
ARG_NAME_OFFSET = 'offset'
ARG_NAME_LIMIT = 'limit'

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PlaybackMode:
    SERVER = 'server'
    BROWSER = 'browser'


class QueueWebSocketClient(NamedTuple):
    """
    A connected /queue/ws client, along with enough of its original request to
    know which queue (the shared server queue, or one particular browser's
    queue) it should be sent on every subsequent broadcast.
    """
    ws: Any
    mode: str
    session_id: str | None


def gzippable_jsonify(content):
    if 'gzip' in request.headers.get('Accept-Encoding', '').lower():
        content = json.dumps(content, separators=(',', ':'))  # avoid whitespace in response
        content = gzip.compress(content.encode('utf-8'), 5)
        response = make_response(content)
        response.headers['Content-Length'] = len(content)
        response.headers['Content-Encoding'] = 'gzip'
        return response
    return jsonify(content)


def normalize_punctuation(search_string):
    return search_string.replace(chr(0x2018), "'")\
                        .replace(chr(0x2019), "'")\
                        .replace(chr(0x201c), '"')\
                        .replace(chr(0x201d), '"')


def response_for_import_playlist(playlist: Playlist, missing_tracks: List[str]):
    response = {
        'playlistid': playlist.Id,
        'nrtracks': len(playlist.Entries),
        'missing': missing_tracks,
    }
    return gzippable_jsonify(response)


def make_options_response(methods):
    response = make_response('', HTTPStatus.NO_CONTENT)
    # Access-Control-Allow-Headers lists headers the *client* may send on the actual
    # request; these are the non-simple headers the webui sends.
    response.headers['Access-Control-Allow-Headers'] = ', '.join(['Content-Type', QUEUE_SESSION_HEADER])
    response.headers['Access-Control-Allow-Methods'] = ', '.join(methods)
    return response


@routes.after_request
def add_security_headers(resp: Response):
    origin = request.headers.get('Origin')
    if origin:
        resp.headers['Access-Control-Allow-Origin'] = origin
    resp.headers['Access-Control-Allow-Credentials'] = 'true'
    return resp


@routes.get("/")
def current_status():
    rtn = get_current_status()
    return gzippable_jsonify(rtn)


@routes.get("/albums/")
def get_all_albums():
    with DatabaseAccess() as db:
        rtn = []
        for album in db.get_all_albums():
            rtn.append(json_album(album, include_tracks=InformationLevel.NO_INFO))
        return gzippable_jsonify(rtn)


@routes.get(RouteConstants.GET_ALBUM)
def get_album(albumid):
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.LINKS)
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_ALBUM_ID) from exc
        return gzippable_jsonify(json_album(album, include_tracks=track_info))


@routes.put("/albums/<albumid>")
def edit_album(albumid):
    data = request.get_json()
    if not data:
        raise BadRequest()
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_ALBUM_ID) from exc
        if year := int(data.get('releasedate', 0)):
            album.ReleaseYear = year
        return ('', HTTPStatus.NO_CONTENT)


@routes.get('/artistaliases/<path:artist>')
def get_artist_aliases(artist):
    with DatabaseAccess() as db:
        aliases = db.get_artist_aliases(artist)
    if not aliases:
        raise NotFound(f"No aliases found for {artist}")
    return gzippable_jsonify(aliases)


@routes.post('/artistaliases/<path:artist>')
def add_artist_alias(artist):
    # The 'also known as' is in the body
    also_known_as = request.get_json()
    if (not also_known_as) or (not isinstance(also_known_as, str)):
        raise BadRequest()
    with DatabaseAccess() as db:
        db.add_artist_alias(artist, also_known_as)
        # And add the reverse mapping, too
        db.add_artist_alias(also_known_as, artist)  # pylint: disable=arguments-out-of-order
    return ('', HTTPStatus.NO_CONTENT)


@routes.delete('/artistaliases/<path:artist>')
def delete_artist_aliases(artist):
    with DatabaseAccess() as db:
        try:
            old_alternatives = db.delete_artist_aliases(artist)
            # Delete the reverse mappings, too
            for alternative in old_alternatives:
                db.remove_one_artist_alias(alternative, artist)
        except NotFoundException as exc:
            raise NotFound(f"No aliases found for artist {artist}") from exc
    return ('', HTTPStatus.NO_CONTENT)


@routes.get(RouteConstants.GET_ARTIST)
def get_artist(artist):
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.LINKS)
    include_aliases = parse_bool(request.args.get('aliases', 'True'))
    exact = parse_bool(request.args.get('exact', 'True'))
    if artist.lower() == 'various artists':
        result = _get_artist_various_artists(artist, track_info)
    else:
        result = _get_artist_real_artist(artist, include_aliases, exact, track_info)
    return gzippable_jsonify(result)


def _get_artist_various_artists(artist: str, track_info: InformationLevel):
    with DatabaseAccess() as db:
        albums = db.get_compilations()
        if not albums:
            raise NotFound("No compilation albums found")
        result = defaultdict(list)
        for album in albums:
            result[artist].append(json_album(album, include_tracks=track_info))
    return result


def _get_artist_real_artist(artist: str, include_aliases: bool, exact: bool, track_info: InformationLevel):
    with DatabaseAccess() as db:
        aliases = db.get_artist_aliases(artist) if include_aliases else []
        albums: Dict[int, Album] = {}  # avoid duplicates if using both inexact searching and aliases
        for lookup_artist in [artist] + aliases:
            artist_albums = db.get_artist(lookup_artist, substring=not exact)
            albums.update((album.Id, album) for album in artist_albums)
        if not albums:
            raise NotFound("No matching artist found")
        result = defaultdict(list)
        for album in albums.values():
            result[album.Artist].append(json_album(album, include_tracks=track_info))
    return result


@routes.get(RouteConstants.GET_ARTWORK)
def get_artwork(artworkid):
    with DatabaseAccess() as db:
        try:
            artwork = db.get_artwork_by_id(artworkid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_ARTWORK_ID) from exc

        if artwork.Path:
            path = Path(artwork.Path)
            mime = mimetypes.types_map.get(path.suffix)
            if mime is None:
                mime = mimetypes.common_types.get(path.suffix)
            with path.open('rb') as handle:
                data = handle.read()

            return Response(data, headers={'Cache-Control': 'max-age=300'}, mimetype=mime)

        elif artwork.Blob:
            if artwork.Blob[:3] == b'\xff\xd8\xff':
                mime = mimetypes.types_map['.jpg']
            elif artwork.Blob[:8] == b'\x89\x50\x4e\x47\x0d\x0a\x1a\x0a':
                mime = mimetypes.types_map['.png']
            else:
                raise InternalServerError("Unknown mime type")

            return Response(artwork.Blob, headers={'Cache-Control': 'max-age=300'}, mimetype=mime)

        else:
            raise NotFound(ERR_MSG_UNKNOWN_ARTWORK_ID)


@routes.get(RouteConstants.GET_ARTWORK_INFO)
def get_artwork_info(artworkid):
    with DatabaseAccess() as db:
        try:
            artwork = db.get_artwork_by_id(artworkid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_ARTWORK_ID) from exc

        has_artwork = (artwork.Path or artwork.Blob)
        rtn = {
            "width": artwork.Width,
            "height": artwork.Height,
            "image": RouteConstants.url_for_get_artwork(artworkid) if has_artwork else None,
        }
        return gzippable_jsonify(rtn)


@routes.get("/downloadhistory")
def get_download_history():
    rtn = []
    for url in current_piju_app.download_history.entries:
        files = current_piju_app.download_history.get_info(url)
        if files:
            # reverse the playlist so most recent is first in the list
            for download_info in reversed(files):
                rtn.append({
                    'url': download_info.url,  # not necessarily the same as url - eg playlist
                    'artist': download_info.artist,
                    'title': download_info.title,
                    'artwork': download_info.artwork
                })
        else:
            rtn.append({'url': url})
    return gzippable_jsonify(rtn)


def get_pagination_arg(arg_name: str, default: int, minimum: int) -> int:
    value = request.args.get(arg_name, '')
    if not value:
        return default
    if not value.isdigit() or int(value) < minimum:
        raise BadRequest(f"Invalid value for {arg_name}")
    return int(value)


def build_pagination(base_url: str, offset: int, limit: int, total: int) -> Dict[str, Any]:
    """
    Describe the page of results that is being returned, including links to the
    adjacent pages; those links preserve the other arguments of the current request.
    """
    def page_link(page_offset):
        args = request.args.to_dict()
        args[ARG_NAME_OFFSET] = page_offset
        args[ARG_NAME_LIMIT] = limit
        return base_url + '?' + urlencode(args)

    return {
        'offset': offset,
        'limit': limit,
        'total': total,
        'next': page_link(offset + limit) if (offset + limit < total) else None,
        'prev': page_link(max(0, offset - limit)) if (offset > 0) else None,
    }


@routes.get("/display_genre/")
def get_all_display_genres():
    with DatabaseAccess() as db:
        album_counts = db.get_display_genre_album_counts()
        return gzippable_jsonify([json_display_genre(display_genre, album_count=album_counts.get(display_genre.Id, 0))
                                  for display_genre in db.get_all_display_genres()])


@routes.get(RouteConstants.GET_DISPLAY_GENRE)
def get_display_genre(displaygenreid):
    album_info = InformationLevel.from_string(request.args.get('albums', ''))
    playlist_info = InformationLevel.from_string(request.args.get('playlists', ''))
    offset = get_pagination_arg(ARG_NAME_OFFSET, default=0, minimum=0)
    limit = min(get_pagination_arg(ARG_NAME_LIMIT, default=DEFAULT_PAGE_SIZE, minimum=1), MAX_PAGE_SIZE)
    with DatabaseAccess() as db:
        try:
            display_genre = db.get_display_genre_by_id(displaygenreid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_DISPLAY_GENRE_ID) from exc
        albums, total = db.get_display_genre_albums(display_genre.Id, offset, limit)
        if playlist_info == InformationLevel.NO_INFO:
            playlists = []
        else:
            playlists = db.get_display_genre_playlists(display_genre.Id)
        pagination = build_pagination(RouteConstants.url_for_get_display_genre(display_genre.Id),
                                      offset, limit, total)
        return gzippable_jsonify(json_display_genre_contents(display_genre,
                                                             albums=albums,
                                                             include_albums=album_info,
                                                             playlists=playlists,
                                                             include_playlists=playlist_info,
                                                             pagination=pagination))


@routes.get("/genres/")
def get_all_genres():
    with DatabaseAccess() as db:
        rtn = []
        for genre in db.get_all_genres():
            rtn.append(json_genre(genre,
                                  include_albums=InformationLevel.NO_INFO,
                                  include_playlists=InformationLevel.NO_INFO))
        return gzippable_jsonify(rtn)


@routes.get(RouteConstants.GET_GENRE)
def get_genre(genreid):
    album_info = InformationLevel.from_string(request.args.get('albums', ''))
    playlist_info = InformationLevel.from_string(request.args.get('playlists', ''))
    with DatabaseAccess() as db:
        try:
            genre = db.get_genre_by_id(genreid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_GENRE_ID) from exc
        return gzippable_jsonify(json_genre(genre, include_albums=album_info, include_playlists=playlist_info))


@routes.put(RouteConstants.GET_GENRE)
def update_genre(genreid):
    display_genre_id = extract_display_genre_id_from_api_data()
    with DatabaseAccess() as db:
        try:
            db.get_genre_by_id(genreid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_GENRE_ID) from exc
        try:
            genre = db.set_genre_display_genre(genreid, display_genre_id)
        except NotFoundException as exc:
            raise BadRequest(ERR_MSG_UNKNOWN_DISPLAY_GENRE_ID) from exc
        # Cached genre and album responses include the display genre, so would now be stale
        clear_cached_responses()
        return gzippable_jsonify(json_genre(genre,
                                            include_albums=InformationLevel.NO_INFO,
                                            include_playlists=InformationLevel.NO_INFO))


@routes.get("/mp3/<trackid>")
def get_mp3(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc

        with open(track.Filepath, 'rb') as handle:
            content = handle.read()
        response = make_response(content)
        response.headers['Content-Type'] = 'audio/mpeg'
        response.headers['Content-Length'] = len(content)
        return response


@routes.post("/player/next")
def update_player_next():
    if current_piju_app.current_player == current_piju_app.file_player:
        current_piju_app.current_player.next()
    else:
        update_player_streaming_prevnext(1)
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/pause")
def update_player_pause():
    current_piju_app.current_player.pause()
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/play")
def update_player_play():
    data = request.get_json()
    if not data:
        raise BadRequest()
    with DatabaseAccess() as db:
        albumid = extract_id(data.get('album'))
        playlistid = extract_id(data.get('playlist'))
        queue_pos = extract_id(data.get('queuepos'))
        trackid = extract_id(data.get('track'))
        radioid = extract_id(data.get('radio'))
        disk_nr = data.get('disk')
        if disk_nr:
            disk_nr = int(disk_nr)
        youtubeurl = data.get('url')

        # Valid requests:
        #   album with at most one of track or disk number
        #   playlist with or without track
        #   queuepos with or without track
        #   track on its own
        #   youtubeurl (with nothing else)
        #   radio (with nothing else)

        if not any([albumid, playlistid, queue_pos, trackid, radioid, youtubeurl]):
            raise BadRequest('Something to play must be specified')

        if sum(x is not None for x in [albumid, playlistid, queue_pos]) > 1:
            raise BadRequest("At most one of album, playlist and queuepos may be specified")

        if radioid and any([albumid, playlistid, queue_pos, trackid, youtubeurl]):
            raise BadRequest("A radio station may not be specified with any other track selection")

        if youtubeurl and any([albumid, playlistid, queue_pos, trackid, radioid]):
            raise BadRequest("A URL may not be specified with any other track selection")

        if youtubeurl:
            update_player_play_from_youtube(youtubeurl)

        elif radioid:
            update_player_play_from_radio(db, radioid)

        else:
            update_player_play_from_local(db, albumid, playlistid, queue_pos, trackid, disk_nr)

    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/previous")
def update_player_prev():
    if current_piju_app.current_player == current_piju_app.file_player:
        current_piju_app.current_player.prev()
    else:
        update_player_streaming_prevnext(-1)
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/resume")
def update_player_resume():
    if request.content_length:
        try:
            data = request.get_json()
            player_type = data.get('player')
        except (AttributeError, KeyError):
            player_type = None
        if player_type == "radio":
            desired_player = current_piju_app.stream_player
        elif player_type == "local":
            desired_player = current_piju_app.file_player
        else:
            raise BadRequest('Request data must be a json object, containing a player key with value radio or local')
        was_playing = select_player(current_piju_app, desired_player)
        if was_playing:
            time.sleep(1)
    else:
        player_type = None

    now_playing = current_piju_app.current_player.resume()
    if (not now_playing) and (player_type == "radio"):
        # start playing the first available radio station
        with DatabaseAccess() as db:
            radio_stations = db.get_all_radio_stations()
            update_player_play_radio_station(radio_stations, 0)

    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/stop")
def update_player_stop():
    current_piju_app.current_player.stop()
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/volume", methods=['OPTIONS'], provide_automatic_options=False)
def volume_options():
    return make_options_response(['GET', 'OPTIONS', 'POST'])


@routes.get("/player/volume", provide_automatic_options=False)
def player_get_volume():
    return {"volume": current_piju_app.current_player.current_volume}


@routes.post("/player/volume", provide_automatic_options=False)
def player_set_volume():
    data = request.get_json()
    if not data:
        raise BadRequest()
    try:
        volume = data.get('volume')
        volume = int(volume)
        for player in (current_piju_app.file_player, current_piju_app.stream_player):
            player.set_volume(volume)
        return ('', HTTPStatus.NO_CONTENT)
    except (AttributeError, KeyError, ValueError) as exc:
        raise BadRequest('Volume must be specified and numeric') from exc


@routes.get("/playlists/")
def get_playlists():
    genre_info = InformationLevel.from_string(request.args.get('genres', ''), InformationLevel.NO_INFO)
    tracks_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.NO_INFO)
    with DatabaseAccess() as db:
        rtn = []
        for playlist in db.get_all_playlists():
            rtn.append(json_playlist(playlist, include_genres=genre_info, include_tracks=tracks_info))
        return gzippable_jsonify(rtn)


@routes.post("/playlists/")
def add_playlist():
    with DatabaseAccess() as db:
        playlist, missing = build_playlist_from_api_data(db)
        db.create_playlist(playlist)
        return response_for_import_playlist(playlist, missing)


@routes.delete("/playlists/<playlistid>")
def delete_playlist(playlistid):
    with DatabaseAccess() as db:
        try:
            db.delete_playlist(playlistid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_PLAYLIST_ID) from exc
        return ('', HTTPStatus.NO_CONTENT)


@routes.get(RouteConstants.GET_ONE_PLAYLIST)
def get_one_playlist(playlistid):
    genre_info = InformationLevel.from_string(request.args.get('genres', ''), InformationLevel.NO_INFO)
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.LINKS)
    with DatabaseAccess() as db:
        try:
            playlist = db.get_playlist_by_id(playlistid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_PLAYLIST_ID) from exc
        return gzippable_jsonify(json_playlist(playlist, include_genres=genre_info, include_tracks=track_info))


@routes.put("/playlists/<playlistid>")
def edit_playlist(playlistid):
    with DatabaseAccess() as db:
        playlist, missing = build_playlist_from_api_data(db)
        try:
            playlist = db.update_playlist(playlistid, playlist)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_PLAYLIST_ID) from exc
        return response_for_import_playlist(playlist, missing)


@routes.delete("/queue/", provide_automatic_options=False)
def queue_delete():
    data = request.get_json()
    if not data:
        raise BadRequest()
    try:
        index = int(data['index'])
        trackid = int(data['track'])
    except KeyError as exc:
        raise BadRequestKeyError() from exc
    except ValueError as exc:
        raise BadRequest() from exc

    mode = request.args.get(ARG_NAME_MODE, PlaybackMode.SERVER)
    match mode:
        case PlaybackMode.SERVER:
            if current_piju_app.current_player != current_piju_app.file_player:
                raise Conflict(ERR_MSG_NO_QUEUE_WHEN_STREAMING)
            if not current_piju_app.current_player.remove_from_queue(index, trackid):
                # index or trackid mismatch
                raise BadRequest('Track id did not match at given index')
        case PlaybackMode.BROWSER:
            current_queue = get_browser_queue(request)
            if (0 <= index < len(current_queue)) and (current_queue[index] == trackid):
                current_queue.pop(index)
                set_browser_queue(request, current_queue)
        case _:
            raise BadRequest()

    current_piju_app.send_queue_update()
    return ('', HTTPStatus.NO_CONTENT)


def format_queue(tracks: list[int]) -> list[Any]:
    with DatabaseAccess() as db:
        # don't (yet?) support fake tracks for browser-based playback
        return [json_track(db.get_track_by_id(trackid)) for trackid in tracks]


def get_server_queue() -> list[Any]:
    """
    Retrieve the server (as opposed to browser) queue
    """
    with DatabaseAccess() as db:
        queue_data = [json_track_or_file(db, queued_track) for
                      queued_track in current_piju_app.current_player.visible_queue]
    return queue_data


def get_requested_queue() -> list[Any]:
    """
    Retrieve whichever of server or browser (session) queue
    is appropriate for the current request. May therefore only
    be called from within an endpoint handler.
    """
    mode = request.args.get(ARG_NAME_MODE, PlaybackMode.SERVER)
    match mode:
        case PlaybackMode.SERVER:
            if current_piju_app.current_player != current_piju_app.file_player:
                raise Conflict(ERR_MSG_NO_QUEUE_WHEN_STREAMING)
            queue_data = get_server_queue()
        case PlaybackMode.BROWSER:
            queue_data = format_queue(get_browser_queue(request))
        case _:
            raise BadRequest()
    return queue_data


@routes.get("/queue/", provide_automatic_options=False)
def queue_get():
    queue_data = get_requested_queue()
    return gzippable_jsonify(queue_data)


def queue_data_for_websocket_client(client: QueueWebSocketClient) -> list[Any]:
    if client.mode == PlaybackMode.BROWSER:
        return format_queue(get_browser_queue_by_session_id(client.session_id))
    return get_server_queue()


@sock.route("/queue/ws", routes)
def queue_websocket_client(ws):
    mode = request.args.get(ARG_NAME_MODE, PlaybackMode.SERVER)
    session_id = session_id_for_request(request) if mode == PlaybackMode.BROWSER else None
    client = QueueWebSocketClient(ws, mode, session_id)
    if sock.app:
        sock.app.queue_websocket_clients.append(client)
    queue_data = get_requested_queue()
    ws.send(json.dumps(queue_data))
    while True:
        _ = ws.receive()
        # discard incoming requests on the websocket for now


@routes.route("/queue/", methods=['OPTIONS'], provide_automatic_options=False)
def queue_options():
    # the request to add to queue looks like a cross-domain request to Chrome,
    # so it sends OPTIONS before the PUT. Hence we need to support this.

    return make_options_response(['DELETE', 'GET', 'OPTIONS', 'PUT'])


@routes.put("/queue/", provide_automatic_options=False)
def queue_put() -> Response:
    data = request.get_json()
    if not data:
        raise BadRequest()

    mode = data.get(ARG_NAME_MODE, PlaybackMode.SERVER)
    if (mode == PlaybackMode.SERVER) and (current_piju_app.current_player != current_piju_app.file_player):
        select_player(current_piju_app, current_piju_app.file_player)

    # there are five different possibilities here:
    #   album: albumid  disk: disknr  # add the tracks from the given disk to queue
    #   album: albumid                # add the given album to queue
    #   track: trackid                # add the given track to queue
    #   url: url                      # add the audio from the given URL to queue
    #   queue: [trackid_or_url]       # reorder the queue
    if albumid := extract_id(data.get('album', '')):
        disknr = extract_id(data.get('disk', ''))
        return queue_put_album(mode, albumid, disknr)

    if trackid := extract_id(data.get('track', '')):
        return queue_put_track(mode, trackid)

    if youtubeurl := data.get('url'):
        return queue_put_youtube(youtubeurl)

    if new_queue_order := data.get('queue'):
        return queue_put_reorder(mode, new_queue_order)

    raise BadRequest("No album+disk id, track id, url or new queue order specified")


def notify_queue_changed(mode: str):
    """
    A server-mode queue mutation is also a playback-state change (it may start
    playback, change the current track, etc), so triggers a full now-playing
    broadcast, which - for players with a queue - includes a queue broadcast.
    A browser-mode mutation doesn't touch server playback at all, so only
    needs its own (per-session) queue broadcast refreshed.
    """
    if mode == PlaybackMode.SERVER:
        current_piju_app.send_now_playing_update()
    else:
        current_piju_app.send_queue_update()


def add_track_to_requested_queue(mode: str, track: Track):
    match mode:
        case PlaybackMode.SERVER:
            add_track_to_queue(track)
        case PlaybackMode.BROWSER:
            current_queue = get_browser_queue(request)
            set_browser_queue(request, current_queue + [track.Id])
        case _:
            raise BadRequest()


def queue_put_album(mode: str, albumid: int, disknr: int | None) -> Response:
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_ALBUM_ID) from exc
        tracks = list(album.Tracks)
        if disknr is not None:
            tracks = [track for track in album.Tracks if track.VolumeNumber == disknr]
        tracks.sort(key=lambda track: (track.VolumeNumber, track.TrackNumber))
        for track in tracks:
            add_track_to_requested_queue(mode, track)
        notify_queue_changed(mode)
    return make_response('', HTTPStatus.NO_CONTENT)


def queue_put_track(mode: str, trackid: int) -> Response:
    with DatabaseAccess() as db:
        try:
            add_track_to_requested_queue(mode, db.get_track_by_id(trackid))
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc
    notify_queue_changed(mode)
    return make_response('', HTTPStatus.NO_CONTENT)


def queue_put_youtube(youtubeurl: str) -> Response:
    if request.args.get(ARG_NAME_MODE, PlaybackMode.SERVER) != PlaybackMode.SERVER:
        raise BadRequest()
    current_piju_app.download_history.add(youtubeurl)
    current_piju_app.work_queue.put((WorkRequests.FETCH_FROM_YOUTUBE,
                                    youtubeurl,
                                    current_piju_app.piju_config.download_dir,
                                    queue_downloaded_files))
    return make_response('', HTTPStatus.NO_CONTENT)


def queue_put_reorder(mode: str, new_queue_order: List[Any]) -> Response:
    new_queue: list[Track | DownloadInfo] = []
    with DatabaseAccess() as db:
        try:
            for trackid in new_queue_order:
                trackid = int(trackid)
                if trackid >= 0:
                    new_queue.append(db.get_track_by_id(trackid))
                else:
                    download_info = DownloadInfoDatabaseSingleton().get_download_info(trackid)
                    if not download_info:
                        raise NotFound()
                    new_queue.append(download_info)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc
        except ValueError as exc:
            raise BadRequest("Unrecognised track id") from exc
        match mode:
            case PlaybackMode.SERVER:
                current_piju_app.current_player.set_queue(new_queue, "/queue/")
            case PlaybackMode.BROWSER:
                set_browser_queue(request, [track.Id for track in new_queue if isinstance(track, Track)])
            case _:
                raise BadRequest()
    notify_queue_changed(mode)
    return make_response('', HTTPStatus.NO_CONTENT)


@routes.get("/radio/", provide_automatic_options=False)
def get_radio_stations():
    with DatabaseAccess() as db:
        rtn = []
        for station in db.get_all_radio_stations():
            rtn.append(json_radio_station(station))
        return gzippable_jsonify(rtn)


@routes.route("/radio/", methods=['OPTIONS'], provide_automatic_options=False)
def radio_stations_options():
    return make_options_response(['GET', 'OPTIONS', 'POST', 'PUT'])


@routes.post("/radio/", provide_automatic_options=False)
def add_radio_station():
    station = build_radio_station_from_api_data()
    with DatabaseAccess() as db:
        db.add_radio_station(station)
        response = {
            'id': station.Id
        }
        return gzippable_jsonify(response)


@routes.put("/radio/", provide_automatic_options=False)
def radio_stations_put():
    # reorder stations
    desired_station_order = request.get_json()
    if not isinstance(desired_station_order, list):
        raise BadRequest("List of station identifiers expected")
    desired_station_order = [extract_id(station) for station in desired_station_order]
    if None in desired_station_order:
        raise BadRequest("Unrecognised station id in list")
    with DatabaseAccess() as db:
        stations = db.get_all_radio_stations()
        if len(desired_station_order) != len(stations) or len(set(desired_station_order)) != len(stations):
            raise BadRequest("Submitted list does not specify the order for all stations, or contains duplicates")
        for station in stations:
            station.SortOrder = desired_station_order.index(station.Id)
    return ('', HTTPStatus.NO_CONTENT)


@routes.delete("/radio/<stationid>")
def delete_one_radio_station(stationid):
    with DatabaseAccess() as db:
        try:
            db.delete_radio_station(stationid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_RADIO_ID) from exc
        return ('', HTTPStatus.NO_CONTENT)


@routes.get(RouteConstants.GET_ONE_RADIO_STATION)
def get_one_radio_station(stationid):
    infolevel = InformationLevel.from_string(request.args.get('urls', ''), InformationLevel.LINKS)
    include_urls = (infolevel in (InformationLevel.ALL_INFO, InformationLevel.DEBUG_INFO))
    with DatabaseAccess() as db:
        try:
            station = db.get_radio_station_by_id(stationid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_RADIO_ID) from exc
        return gzippable_jsonify(json_radio_station(station, include_urls=include_urls))


@routes.put("/radio/<stationid>")
def edit_radio_station(stationid):
    station = build_radio_station_from_api_data()
    with DatabaseAccess() as db:
        try:
            existing_station = db.update_radio_station(stationid, station)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_RADIO_ID) from exc
        return gzippable_jsonify(json_radio_station(existing_station))


@routes.post("/scanner/scan")
def start_scan():
    data = request.get_json()
    if data is None:
        raise BadRequest()
    subdir = data.get('dir')
    scandir = os.path.join(current_piju_app.piju_config.music_dir, subdir if subdir else '')
    if not os.path.isdir(scandir):
        raise BadRequest(f"Directory {subdir} does not exist")
    current_piju_app.work_queue.put((WorkRequests.SCAN_DIRECTORY, scandir))
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/scanner/tidy")
def start_tidy():
    current_piju_app.work_queue.put((WorkRequests.DELETE_MISSING_TRACKS, ))
    current_piju_app.work_queue.put((WorkRequests.DELETE_ALBUMS_WITHOUT_TRACKS, ))
    current_piju_app.work_queue.put((WorkRequests.DELETE_EMPTY_GENRES, ))
    current_piju_app.work_queue.put((WorkRequests.DELETE_ARTWORK_WITHOUT_TRACKS, ))
    return ('', HTTPStatus.NO_CONTENT)


@routes.get("/search/")
def search():
    search_string = request.args.get('q', None)
    if not search_string:
        raise BadRequest()
    search_words = normalize_punctuation(search_string).strip().split()
    do_search_albums = parse_bool(request.args.get('albums', 'True'))
    do_search_artists = parse_bool(request.args.get('artists', 'True'))
    do_search_tracks = parse_bool(request.args.get('tracks', 'True'))
    with DatabaseAccess() as db:
        rtn = {}
        if do_search_albums:
            albums = db.search_for_albums(search_words)
            rtn['albums'] = [json_album(album, include_tracks=InformationLevel.NO_INFO) for album in albums]

        if do_search_artists:
            artist_albums = db.search_for_artist(search_words)
            artists = {album.Artist for album in artist_albums if album.Artist}
            rtn['artists'] = [{"name": artist, "link": RouteConstants.url_for_get_artist(artist)}
                              for artist in artists]
        if do_search_tracks:
            tracks = db.search_for_tracks(search_words)
            rtn['tracks'] = [json_track(track) for track in tracks]
    return gzippable_jsonify(rtn)


@routes.get("/tracks/")
def get_all_tracks():
    limit = request.args.get('limit', '')
    if limit and limit.isdigit():
        limit = int(limit)
    else:
        limit = None
    with DatabaseAccess() as db:
        rtn = []
        for track in db.get_all_tracks(limit):
            rtn.append(json_track(track))
        return gzippable_jsonify(rtn)


@routes.get(RouteConstants.GET_TRACK)
def get_track(trackid):
    infolevel = InformationLevel.from_string(request.args.get('infolevel', ''), InformationLevel.ALL_INFO)
    include_debuginfo = (infolevel == InformationLevel.DEBUG_INFO)
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc
        return gzippable_jsonify(json_track(track, include_debuginfo=include_debuginfo))


@sock.route('/ws', routes)
def currentstatus_websocket_client(ws):
    if sock.app:
        sock.app.status_websocket_clients.append(ws)
    data = get_current_status()
    ws.send(json.dumps(data))
    while True:
        _ = ws.receive()
        # discard incoming requests on the websocket for now
