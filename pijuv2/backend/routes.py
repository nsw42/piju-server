from collections import defaultdict
import gzip
from http import HTTPStatus
import json
import mimetypes
import os.path
from pathlib import Path
import time
from typing import List

from flask import Blueprint, current_app, jsonify, make_response, request, Response, url_for
from flask_sock import Sock
from werkzeug.exceptions import BadRequest, BadRequestKeyError, Conflict, InternalServerError, NotFound

from ..database.database import DatabaseAccess, NotFoundException
from ..database.schema import Playlist
from .downloadinfo import DownloadInfoDatabaseSingleton
from .deserialize import build_playlist_from_api_data, build_radio_station_from_api_data, extract_id, parse_bool
from .nowplaying import get_current_status
from .playerctrl import add_track_to_queue, queue_downloaded_files, select_player
from .playerctrl import update_player_play_from_local, update_player_play_from_radio, update_player_play_from_youtube
from .playerctrl import update_player_streaming_prevnext
from .serialize import json_genre, json_playlist, json_track_or_file
from .serialize import InformationLevel
from .serialize import json_album, json_radio_station, json_track
from .workrequests import WorkRequests

routes = Blueprint('routes', __name__, url_prefix='')
sock = Sock()

ERR_MSG_UNKNOWN_ALBUM_ID = 'Unknown album id'
ERR_MSG_UNKNOWN_GENRE_ID = 'Unknown genre id'
ERR_MSG_UNKNOWN_TRACK_ID = 'Unknown track id'
ERR_MSG_UNKNOWN_PLAYLIST_ID = 'Unknown playlist id'
ERR_MSG_UNKNOWN_RADIO_ID = 'Unknown radio station id'
ERR_MSG_NO_QUEUE_WHEN_STREAMING = "Queue operations not permitted when playing streaming content"


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


@routes.after_request
def add_security_headers(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
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
            rtn.append(json_album(album, include_tracks=InformationLevel.NoInfo))
        return gzippable_jsonify(rtn)


@routes.get("/albums/<albumid>")
def get_album(albumid):
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
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


# Pretend artist is a full-path, so we correctly handle bands like 'AC/DC'
@routes.get("/artists/<path:artist>")
def get_artist(artist):
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
    exact = parse_bool(request.args.get('exact', 'True'))
    with DatabaseAccess() as db:
        if artist.lower() == 'various artists':
            albums = db.get_compilations()
            if not albums:
                raise NotFound("No compilation albums found")
            result = defaultdict(list)
            for album in albums:
                result[artist].append(json_album(album, include_tracks=track_info))
        else:
            albums = db.get_artist(artist, substring=not exact)
            if not albums:
                raise NotFound("No matching artist found")
            result = defaultdict(list)
            for album in albums:
                result[album.Artist].append(json_album(album, include_tracks=track_info))
    return gzippable_jsonify(result)


@routes.get("/artwork/<artworkid>")
def get_artwork(artworkid):
    with DatabaseAccess() as db:
        try:
            artwork = db.get_artwork_by_id(artworkid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc

        if artwork.Path:
            path = Path(artwork.Path)
            mime = mimetypes.types_map.get(path.suffix)
            if mime is None:
                mime = mimetypes.common_types.get(path.suffix)
            with open(artwork.Path, 'rb') as handle:
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
            raise NotFound("Unknown artwork id")


@routes.get("/artworkinfo/<artworkid>")
def get_artwork_info(artworkid):
    with DatabaseAccess() as db:
        try:
            artwork = db.get_artwork_by_id(artworkid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc

        has_artwork = (artwork.Path or artwork.Blob)
        rtn = {
            "width": artwork.Width,
            "height": artwork.Height,
            "image": url_for('routes.get_artwork', artworkid=artworkid) if has_artwork else None,
        }
        return gzippable_jsonify(rtn)


@routes.get("/downloadhistory")
def get_download_history():
    rtn = []
    for url in current_app.download_history.entries:
        files = current_app.download_history.get_info(url)
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


@routes.get("/genres/")
def get_all_genres():
    with DatabaseAccess() as db:
        rtn = []
        for genre in db.get_all_genres():
            rtn.append(json_genre(genre,
                                  include_albums=InformationLevel.NoInfo,
                                  include_playlists=InformationLevel.NoInfo))
        return gzippable_jsonify(rtn)


@routes.get("/genres/<genreid>")
def get_genre(genreid):
    album_info = InformationLevel.from_string(request.args.get('albums', ''))
    playlist_info = InformationLevel.from_string(request.args.get('playlists', ''))
    with DatabaseAccess() as db:
        try:
            genre = db.get_genre_by_id(genreid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_GENRE_ID) from exc
        return gzippable_jsonify(json_genre(genre, include_albums=album_info, include_playlists=playlist_info))


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
    if current_app.current_player == current_app.file_player:
        current_app.current_player.next()
    else:
        update_player_streaming_prevnext(1)
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/pause")
def update_player_pause():
    current_app.current_player.pause()
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
    if current_app.current_player == current_app.file_player:
        current_app.current_player.prev()
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
            desired_player = current_app.stream_player
        elif player_type == "local":
            desired_player = current_app.file_player
        else:
            raise BadRequest('Request data must be a json object, containing a player key with value radio or local')
        was_playing = select_player(current_app, desired_player)
        if was_playing:
            time.sleep(1)
    current_app.current_player.resume()
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/player/stop")
def update_player_stop():
    current_app.current_player.stop()
    return ('', HTTPStatus.NO_CONTENT)


@routes.get("/player/volume")
def player_get_volume():
    return {"volume": current_app.current_player.current_volume}


@routes.post("/player/volume")
def player_set_volume():
    data = request.get_json()
    if not data:
        raise BadRequest()
    try:
        volume = data.get('volume')
        volume = int(volume)
        for player in (current_app.file_player, current_app.stream_player):
            player.set_volume(volume)
        return ('', HTTPStatus.NO_CONTENT)
    except (AttributeError, KeyError, ValueError) as exc:
        raise BadRequest('Volume must be specified and numeric') from exc


@routes.get("/playlists/")
def get_playlists():
    genre_info = InformationLevel.from_string(request.args.get('genres', ''), InformationLevel.NoInfo)
    tracks_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.NoInfo)
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


@routes.get("/playlists/<playlistid>")
def get_one_playlist(playlistid):
    genre_info = InformationLevel.from_string(request.args.get('genres', ''), InformationLevel.NoInfo)
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
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
        playlist = db.update_playlist(playlistid, playlist)
        return response_for_import_playlist(playlist, missing)


@routes.delete("/queue/", provide_automatic_options=False)
def queue_delete():
    if current_app.current_player != current_app.file_player:
        raise Conflict(ERR_MSG_NO_QUEUE_WHEN_STREAMING)
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
    if not current_app.current_player.remove_from_queue(index, trackid):
        # index or trackid mismatch
        raise BadRequest('Track id did not match at given index')
    return ('', HTTPStatus.NO_CONTENT)


@routes.get("/queue/", provide_automatic_options=False)
def queue_get():
    if current_app.current_player != current_app.file_player:
        raise Conflict(ERR_MSG_NO_QUEUE_WHEN_STREAMING)
    with DatabaseAccess() as db:
        queue_data = [json_track_or_file(db, queued_track) for
                      queued_track in current_app.current_player.visible_queue]
    return gzippable_jsonify(queue_data)


@routes.route("/queue/", methods=['OPTIONS'], provide_automatic_options=False)
def queue_options():
    if current_app.current_player != current_app.file_player:
        raise Conflict(ERR_MSG_NO_QUEUE_WHEN_STREAMING)

    # the request to add to queue looks like a cross-domain request to Chrome,
    # so it sends OPTIONS before the PUT. Hence we need to support this.
    response = make_response('', HTTPStatus.NO_CONTENT)
    response.headers['Access-Control-Allow-Headers'] = '*'  # Maybe tighten this up?
    response.headers['Access-Control-Allow-Methods'] = ', '.join(['DELETE', 'GET', 'OPTIONS', 'PUT'])
    return response


@routes.put("/queue/", provide_automatic_options=False)
def queue_put():
    if current_app.current_player != current_app.file_player:
        raise Conflict(ERR_MSG_NO_QUEUE_WHEN_STREAMING)

    data = request.get_json()
    if not data:
        raise BadRequest()

    # there are four different possibilities here:
    #   album: albumid  disk: disknr  # add the tracks from the given disk to queue
    #   track: trackid                # add the given track to queue
    #   url: url                      # add the audio from the given URL to queue
    #   queue: [trackid_or_url]       # reorder the queue
    if (albumid := extract_id(data.get('album', ''))) and (disknr := extract_id(data.get('disk', ''))):
        return queue_put_album(albumid, disknr)

    if trackid := extract_id(data.get('track', '')):
        return queue_put_track(trackid)

    if youtubeurl := data.get('url'):
        return queue_put_youtube(youtubeurl)

    if new_queue_order := data.get('queue'):
        return queue_put_reorder(new_queue_order)

    raise BadRequest("No album+disk id, track id, url or new queue order specified")


def queue_put_album(albumid: int, disknr: int):
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_ALBUM_ID) from exc
        tracks = [track for track in album.Tracks if track.VolumeNumber == disknr]
        tracks.sort(key=lambda track: (track.VolumeNumber, track.TrackNumber))
        for track in tracks:
            print("Queuing track", track.Title)
            add_track_to_queue(track)
    return ('', HTTPStatus.NO_CONTENT)


def queue_put_track(trackid: int):
    with DatabaseAccess() as db:
        try:
            add_track_to_queue(db.get_track_by_id(trackid))
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc
    return ('', HTTPStatus.NO_CONTENT)


def queue_put_youtube(youtubeurl: str):
    current_app.download_history.add(youtubeurl)
    current_app.work_queue.put((WorkRequests.FETCH_FROM_YOUTUBE,
                                youtubeurl,
                                current_app.piju_config.download_dir,
                                queue_downloaded_files))
    return ('', HTTPStatus.NO_CONTENT)


def queue_put_reorder(new_queue_order: List[any]):
    new_queue = []
    with DatabaseAccess() as db:
        try:
            for trackid in new_queue_order:
                trackid = int(trackid)
                if trackid >= 0:
                    new_queue.append(db.get_track_by_id(trackid))
                else:
                    new_queue.append(DownloadInfoDatabaseSingleton().get_download_info(trackid))
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc
        except ValueError as exc:
            raise BadRequest("Unrecognised track id") from exc
        current_app.current_player.set_queue(new_queue, "/queue/")
    return ('', HTTPStatus.NO_CONTENT)


@routes.get("/radio/", provide_automatic_options=False)
def get_radio_stations():
    with DatabaseAccess() as db:
        rtn = []
        for station in db.get_all_radio_stations():
            rtn.append(json_radio_station(station))
        return gzippable_jsonify(rtn)


@routes.route("/radio/", methods=['OPTIONS'], provide_automatic_options=False)
def radio_stations_options():
    response = make_response('', HTTPStatus.NO_CONTENT)
    response.headers['Access-Control-Allow-Headers'] = ', '.join(['Content-Type',
                                                                  'Access-Control-Allow-Headers',
                                                                  'Access-Control-Allow-Methods',
                                                                  'Access-Control-Allow-Origin'])
    response.headers['Access-Control-Allow-Methods'] = ', '.join(['GET', 'OPTIONS', 'POST', 'PUT'])
    return response


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


@routes.get("/radio/<stationid>")
def get_one_radio_station(stationid):
    infolevel = InformationLevel.from_string(request.args.get('urls', ''), InformationLevel.Links)
    include_urls = (infolevel in (InformationLevel.AllInfo, InformationLevel.DebugInfo))
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
        existing_station = db.update_radio_station(stationid, station)
        return gzippable_jsonify(json_radio_station(existing_station))


@routes.post("/scanner/scan")
def start_scan():
    data = request.get_json()
    if data is None:
        raise BadRequest()
    subdir = data.get('dir')
    scandir = os.path.join(current_app.piju_config.music_dir, subdir if subdir else '')
    if not os.path.isdir(scandir):
        raise BadRequest(f"Directory {subdir} does not exist")
    current_app.work_queue.put((WorkRequests.SCAN_DIRECTORY, scandir))
    return ('', HTTPStatus.NO_CONTENT)


@routes.post("/scanner/tidy")
def start_tidy():
    current_app.work_queue.put((WorkRequests.DELETE_MISSING_TRACKS, ))
    current_app.work_queue.put((WorkRequests.DELETE_ALBUMS_WITHOUT_TRACKS, ))
    return ('', HTTPStatus.NO_CONTENT)


@routes.get("/search/<search_string>")
def search(search_string):
    search_words = normalize_punctuation(search_string).strip().split()
    do_search_albums = parse_bool(request.args.get('albums', 'True'))
    do_search_artists = parse_bool(request.args.get('artists', 'True'))
    do_search_tracks = parse_bool(request.args.get('tracks', 'True'))
    with DatabaseAccess() as db:
        rtn = {}
        if do_search_albums:
            albums = db.search_for_albums(search_words)
            rtn['albums'] = [json_album(album, include_tracks=InformationLevel.NoInfo) for album in albums]
        if do_search_artists:
            artist_albums = db.search_for_artist(search_words)
            artists = set(album.Artist for album in artist_albums if album.Artist)
            rtn['artists'] = [{"name": artist, "link": url_for('routes.get_artist', artist=artist)}
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


@routes.get("/tracks/<trackid>")
def get_track(trackid):
    infolevel = InformationLevel.from_string(request.args.get('infolevel', ''), InformationLevel.AllInfo)
    include_debuginfo = (infolevel == InformationLevel.DebugInfo)
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException as exc:
            raise NotFound(ERR_MSG_UNKNOWN_TRACK_ID) from exc
        return gzippable_jsonify(json_track(track, include_debuginfo=include_debuginfo))


@sock.route('/ws', routes)
def websocket_client(ws):
    sock.app.websocket_clients.append(ws)
    data = get_current_status()
    ws.send(json.dumps(data))
    while True:
        _ = ws.receive()
        # discard incoming requests on the websocket for now
