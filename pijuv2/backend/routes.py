from collections import defaultdict
import gzip
from http import HTTPStatus
import json
import mimetypes
import os.path
from pathlib import Path
from typing import List

from flask import abort, Blueprint, current_app, jsonify, make_response, request, Response, url_for
from werkzeug.exceptions import BadRequest, BadRequestKeyError

from ..database.database import DatabaseAccess, NotFoundException
from ..database.schema import Playlist
from ..player.playerinterface import CurrentStatusStrings
from .downloadinfo import DownloadInfoDatabaseSingleton
from .deserialize import build_playlist_from_api_data, build_radio_station_from_api_data, extract_id, parse_bool
from .playerctrl import add_track_to_queue, queue_downloaded_files, select_player, update_player_play_album
from .playerctrl import update_player_play_from_queue, update_player_play_from_radio, update_player_play_from_youtube
from .playerctrl import update_player_play_playlist, update_player_play_track, update_player_streaming_prevnext
from .serialize import json_genre, json_playlist, json_track_or_file
from .serialize import InformationLevel
from .serialize import json_album, json_radio_station, json_track
from .workrequests import WorkRequests

routes = Blueprint('routes', __name__, url_prefix='')

ERR_MSG_UNKNOWN_ALBUM_ID = 'Unknown album id'
ERR_MSG_UNKNOWN_GENRE_ID = 'Unknown genre id'
ERR_MSG_UNKNOWN_TRACK_ID = 'Unknown track id'
ERR_MSG_UNKNOWN_PLAYLIST_ID = 'Unknown playlist id'
ERR_MSG_UNKNOWN_RADIO_ID = 'Unknown radio station id'


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


@routes.route("/")
def current_status():
    with DatabaseAccess() as db:
        c_p = current_app.current_player
        rtn = {
            'WorkerStatus': current_app.worker.current_status,
            'PlayerStatus': c_p.current_status,
            'PlayerVolume': c_p.current_volume,
            'NumberAlbums': db.get_nr_albums(),
            'NumberTracks': db.get_nr_tracks(),
            'CurrentTrackIndex': None if (c_p.current_track_index is None) else (c_p.current_track_index + 1),
            'MaximumTrackIndex': c_p.number_of_tracks,
            'ApiVersion': current_app.api_version_string,
        }
        if c_p == current_app.file_player:
            rtn['CurrentTracklistUri'] = c_p.current_tracklist_identifier
            if c_p.current_track:
                rtn['CurrentTrack'] = json_track_or_file(db, c_p.current_track)
                rtn['CurrentArtwork'] = rtn['CurrentTrack']['artwork']
            else:
                rtn['CurrentTrack'] = {}
                rtn['CurrentArtwork'] = None
        elif c_p == current_app.stream_player:
            rtn['CurrentStream'] = c_p.currently_playing_name
            rtn['CurrentArtwork'] = c_p.currently_playing_artwork
            if c_p.current_status == CurrentStatusStrings.PLAYING and c_p.now_playing_artist and c_p.now_playing_track:
                rtn['CurrentTrack'] = {
                    'artist': c_p.now_playing_artist,
                    'title': c_p.now_playing_track
                }

    return gzippable_jsonify(rtn)


@routes.route("/albums/")
def get_all_albums():
    with DatabaseAccess() as db:
        rtn = []
        for album in db.get_all_albums():
            rtn.append(json_album(album, include_tracks=InformationLevel.NoInfo))
        return gzippable_jsonify(rtn)


@routes.route("/albums/<albumid>")
def get_album(albumid):
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
    with DatabaseAccess() as db:
        try:
            album = db.get_album_by_id(albumid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_ALBUM_ID)
        return gzippable_jsonify(json_album(album, include_tracks=track_info))


@routes.route("/artists/<artist>")
def get_artist(artist):
    track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
    exact = parse_bool(request.args.get('exact', 'True'))
    with DatabaseAccess() as db:
        albums = db.get_artist(artist, substring=not exact)
        if not albums:
            abort(HTTPStatus.NOT_FOUND, description="No matching artist found")
        result = defaultdict(list)
        for album in albums:
            result[album.Artist].append(json_album(album, include_tracks=track_info))
        return gzippable_jsonify(result)


@routes.route("/artwork/<trackid>")
def get_artwork(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_TRACK_ID)

        if track.ArtworkPath:
            path = Path(track.ArtworkPath)
            mime = mimetypes.types_map[path.suffix]
            with open(track.ArtworkPath, 'rb') as handle:
                data = handle.read()

            return Response(data, headers={'Cache-Control': 'max-age=300'}, mimetype=mime)

        elif track.ArtworkBlob:
            if track.ArtworkBlob[:3] == b'\xff\xd8\xff':
                mime = mimetypes.types_map['.jpg']
            elif track.ArtworkBlob[:8] == b'\x89\x50\x4e\x47\x0d\x0a\x1a\x0a':
                mime = mimetypes.types_map['.png']
            else:
                abort(500, description="Unknown mime type")

            return Response(track.ArtworkBlob, headers={'Cache-Control': 'max-age=300'}, mimetype=mime)

        else:
            return abort(HTTPStatus.NOT_FOUND, description="Track has no artwork")


@routes.route("/artworkinfo/<trackid>")
def get_artwork_info(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_TRACK_ID)

        has_artwork = (track.ArtworkPath or track.ArtworkBlob)
        rtn = {
            "width": track.ArtworkWidth,
            "height": track.ArtworkHeight,
            "image": url_for('routes.get_artwork', trackid=trackid) if has_artwork else None,
        }
        return gzippable_jsonify(rtn)


@routes.route("/downloadhistory")
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


@routes.route("/genres/")
def get_all_genres():
    with DatabaseAccess() as db:
        rtn = []
        for genre in db.get_all_genres():
            rtn.append(json_genre(genre,
                                  include_albums=InformationLevel.NoInfo,
                                  include_playlists=InformationLevel.NoInfo))
        return gzippable_jsonify(rtn)


@routes.route("/genres/<genreid>")
def get_genre(genreid):
    album_info = InformationLevel.from_string(request.args.get('albums', ''))
    playlist_info = InformationLevel.from_string(request.args.get('playlists', ''))
    with DatabaseAccess() as db:
        try:
            genre = db.get_genre_by_id(genreid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_GENRE_ID)
        return gzippable_jsonify(json_genre(genre, include_albums=album_info, include_playlists=playlist_info))


@routes.route("/mp3/<trackid>")
def get_mp3(trackid):
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_TRACK_ID)

        with open(track.Filepath, 'rb') as handle:
            content = handle.read()
        response = make_response(content)
        response.headers['Content-Type'] = 'audio/mpeg'
        response.headers['Content-Length'] = len(content)
        return response


@routes.route("/player/next", methods=['POST'])
def update_player_next():
    if current_app.current_player == current_app.file_player:
        current_app.current_player.next()
    else:
        update_player_streaming_prevnext(1)
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/pause", methods=['POST'])
def update_player_pause():
    current_app.current_player.pause()
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/play", methods=['POST'])
def update_player_play():
    data = request.get_json()
    if not data:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    with DatabaseAccess() as db:
        albumid = extract_id(data.get('album'))
        playlistid = extract_id(data.get('playlist'))
        queue_pos = extract_id(data.get('queuepos'))
        trackid = extract_id(data.get('track'))
        radioid = extract_id(data.get('radio'))
        youtubeurl = data.get('url')

        # Valid requests:
        #   album with or without track
        #   playlist with or without track
        #   queuepos with or without track
        #   track on its own
        #   youtubeurl (with nothing else)
        #   radio (with nothing else)

        if not any([albumid, playlistid, queue_pos, trackid, radioid, youtubeurl]):
            abort(HTTPStatus.BAD_REQUEST, description='Something to play must be specified')

        if sum(x is not None for x in [albumid, playlistid, queue_pos]) > 1:
            abort(HTTPStatus.BAD_REQUEST, "At most one of album, playlist and queuepos may be specified")

        if radioid and any([albumid, playlistid, queue_pos, trackid, youtubeurl]):
            abort(HTTPStatus.BAD_REQUEST, "A radio station may not be specified with any other track selection")

        if youtubeurl and any([albumid, playlistid, queue_pos, trackid, radioid]):
            abort(HTTPStatus.BAD_REQUEST, "A URL may not be specified with any other track selection")

        if youtubeurl:
            update_player_play_from_youtube(youtubeurl)

        elif radioid:
            update_player_play_from_radio(db, radioid)

        else:
            # File-based playback required
            select_player(current_app, current_app.file_player)

            if albumid is not None:
                update_player_play_album(db, albumid, trackid)

            elif playlistid is not None:
                update_player_play_playlist(db, playlistid, trackid)

            elif queue_pos is not None:
                update_player_play_from_queue(queue_pos, trackid)

            elif trackid:
                update_player_play_track(db, trackid)

            else:
                assert False, "Internal error: Unhandled code path"

    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/previous", methods=['POST'])
def update_player_prev():
    if current_app.current_player == current_app.file_player:
        current_app.current_player.prev()
    else:
        update_player_streaming_prevnext(-1)
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/resume", methods=['POST'])
def update_player_resume():
    current_app.current_player.resume()
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/stop", methods=['POST'])
def update_player_stop():
    current_app.current_player.stop()
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/player/volume", methods=['GET', 'POST'])
def player_volume():
    if request.method == 'GET':
        return {"volume": current_app.current_player.current_volume}

    elif request.method == 'POST':
        data = request.get_json()
        if not data:
            abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
        try:
            volume = data.get('volume')
            volume = int(volume)
            for player in (current_app.file_player, current_app.stream_player):
                player.set_volume(volume)
            return ('', HTTPStatus.NO_CONTENT)
        except (AttributeError, KeyError, ValueError):
            abort(HTTPStatus.BAD_REQUEST, description='Volume must be specified and numeric')

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@routes.route("/playlists/", methods=['GET', 'POST'])
def playlists():
    if request.method == 'GET':
        genre_info = InformationLevel.from_string(request.args.get('genres', ''), InformationLevel.NoInfo)
        tracks_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.NoInfo)
        with DatabaseAccess() as db:
            rtn = []
            for playlist in db.get_all_playlists():
                rtn.append(json_playlist(playlist, include_genres=genre_info, include_tracks=tracks_info))
            return gzippable_jsonify(rtn)

    elif request.method == 'POST':
        with DatabaseAccess() as db:
            playlist, missing = build_playlist_from_api_data(db)
            db.create_playlist(playlist)
            return response_for_import_playlist(playlist, missing)

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@routes.route("/playlists/<playlistid>", methods=['DELETE', 'GET', 'PUT'])
def one_playlist(playlistid):
    if request.method == 'GET':
        genre_info = InformationLevel.from_string(request.args.get('genres', ''), InformationLevel.NoInfo)
        track_info = InformationLevel.from_string(request.args.get('tracks', ''), InformationLevel.Links)
        with DatabaseAccess() as db:
            try:
                playlist = db.get_playlist_by_id(playlistid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_PLAYLIST_ID)
            return gzippable_jsonify(json_playlist(playlist, include_genres=genre_info, include_tracks=track_info))

    elif request.method == 'PUT':
        with DatabaseAccess() as db:
            playlist, missing = build_playlist_from_api_data(db)
            playlist = db.update_playlist(playlistid, playlist)
            return response_for_import_playlist(playlist, missing)

    elif request.method == 'DELETE':
        with DatabaseAccess() as db:
            try:
                db.delete_playlist(playlistid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_PLAYLIST_ID)
            return ('', HTTPStatus.NO_CONTENT)

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@routes.route("/queue/", methods=['GET', 'DELETE', 'OPTIONS', 'PUT'])
def queue():
    if current_app.current_player != current_app.file_player:
        abort(HTTPStatus.CONFLICT, "Queue operations not permitted when playing streaming content")
    if request.method == 'DELETE':
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

    elif request.method == 'GET':
        with DatabaseAccess() as db:
            queue_data = [json_track_or_file(db, queued_track) for
                          queued_track in current_app.current_player.visible_queue]
        return gzippable_jsonify(queue_data)

    elif request.method == 'OPTIONS':
        # the request to add to queue looks like a cross-domain request to Chrome,
        # so it sends OPTIONS before the PUT. Hence we need to support this.
        response = make_response('', HTTPStatus.NO_CONTENT)
        response.headers['Access-Control-Allow-Headers'] = '*'  # Maybe tighten this up?
        response.headers['Access-Control-Allow-Methods'] = ', '.join(request.url_rule.methods)
        return response

    elif request.method == 'PUT':
        data = request.get_json()
        if not data:
            abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
        # there are three different possibilities here:
        #   track: trackid  # add the given track to queue
        #   url: url        # add the audio from the given URL to queue
        #   queue: [trackid_or_url]  # reorder the queue
        if trackid := extract_id(data.get('track', '')):
            with DatabaseAccess() as db:
                try:
                    add_track_to_queue(db.get_track_by_id(trackid))
                except NotFoundException:
                    abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_TRACK_ID)
        elif youtubeurl := data.get('url'):
            current_app.download_history.add(youtubeurl)
            current_app.work_queue.put((WorkRequests.FETCH_FROM_YOUTUBE,
                                        youtubeurl,
                                        current_app.piju_config.download_dir,
                                        queue_downloaded_files))
        elif new_queue_order := data.get('queue'):
            new_queue = []
            with DatabaseAccess() as db:
                try:
                    for trackid in new_queue_order:
                        trackid = int(trackid)
                        if trackid >= 0:
                            new_queue.append(db.get_track_by_id(trackid))
                        else:
                            new_queue.append(DownloadInfoDatabaseSingleton().get_download_info(trackid))
                except NotFoundException:
                    abort(HTTPStatus.NOT_FOUND, ERR_MSG_UNKNOWN_TRACK_ID)
                except ValueError:
                    abort(HTTPStatus.BAD_REQUEST, "Unrecognised track id")
                current_app.current_player.set_queue(new_queue, "/queue/")
        else:
            abort(HTTPStatus.BAD_REQUEST, "No track id, url or new queue order specified")
        return ('', HTTPStatus.NO_CONTENT)

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@routes.route("/radio/", methods=['GET', 'OPTIONS', 'POST', 'PUT'])
def radio_stations():
    if request.method == 'GET':
        with DatabaseAccess() as db:
            rtn = []
            for station in db.get_all_radio_stations():
                rtn.append(json_radio_station(station))
            return gzippable_jsonify(rtn)

    elif request.method == 'OPTIONS':
        response = make_response('', HTTPStatus.NO_CONTENT)
        response.headers['Access-Control-Allow-Headers'] = ', '.join(['Content-Type',
                                                                      'Access-Control-Allow-Headers',
                                                                      'Access-Control-Allow-Methods',
                                                                      'Access-Control-Allow-Origin'])
        response.headers['Access-Control-Allow-Methods'] = ', '.join(request.url_rule.methods)

    elif request.method == 'POST':
        station = build_radio_station_from_api_data()
        with DatabaseAccess() as db:
            db.add_radio_station(station)
            response = {
                'id': station.Id
            }
            return gzippable_jsonify(response)

    elif request.method == 'PUT':
        # reorder stations
        desired_station_order = request.get_json()
        if not isinstance(desired_station_order, list):
            abort(HTTPStatus.BAD_REQUEST, "List of station identifiers expected")
        desired_station_order = [extract_id(station) for station in desired_station_order]
        if None in desired_station_order:
            abort(HTTPStatus.BAD_REQUEST, "Unrecognised station id in list")
        with DatabaseAccess() as db:
            stations = db.get_all_radio_stations()
            if len(desired_station_order) != len(stations) or len(set(desired_station_order)) != len(stations):
                msg = "Submitted list does not specify the order for all stations, or contains duplicates"
                abort(HTTPStatus.BAD_REQUEST, msg)
            for station in stations:
                station.SortOrder = desired_station_order.index(station.Id)
        return ('', HTTPStatus.NO_CONTENT)

    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@routes.route("/radio/<stationid>", methods=['DELETE', 'GET', 'PUT'])
def one_radio_station(stationid):
    if request.method == 'GET':
        infolevel = InformationLevel.from_string(request.args.get('urls', ''), InformationLevel.Links)
        include_urls = (infolevel in (InformationLevel.AllInfo, InformationLevel.DebugInfo))
        with DatabaseAccess() as db:
            try:
                station = db.get_radio_station_by_id(stationid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_RADIO_ID)
            return gzippable_jsonify(json_radio_station(station, include_urls=include_urls))

    elif request.method == 'PUT':
        station = build_radio_station_from_api_data()
        with DatabaseAccess() as db:
            existing_station = db.update_radio_station(stationid, station)
            return gzippable_jsonify(json_radio_station(existing_station))

    elif request.method == 'DELETE':
        with DatabaseAccess() as db:
            try:
                db.delete_radio_station(stationid)
            except NotFoundException:
                abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_RADIO_ID)
            return ('', HTTPStatus.NO_CONTENT)
    return ('', HTTPStatus.INTERNAL_SERVER_ERROR)


@routes.route("/scanner/scan", methods=['POST'])
def start_scan():
    data = request.get_json()
    if data is None:
        abort(HTTPStatus.BAD_REQUEST, description='No data found in request')
    subdir = data.get('dir')
    scandir = os.path.join(current_app.piju_config.music_dir, subdir if subdir else '')
    if not os.path.isdir(scandir):
        abort(HTTPStatus.BAD_REQUEST, f"Directory {subdir} does not exist")
    current_app.work_queue.put((WorkRequests.SCAN_DIRECTORY, scandir))
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/scanner/tidy", methods=['POST'])
def start_tidy():
    current_app.work_queue.put((WorkRequests.DELETE_MISSING_TRACKS, ))
    current_app.work_queue.put((WorkRequests.DELETE_ALBUMS_WITHOUT_TRACKS, ))
    return ('', HTTPStatus.NO_CONTENT)


@routes.route("/search/<search_string>")
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


@routes.route("/tracks/")
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


@routes.route("/tracks/<trackid>")
def get_track(trackid):
    infolevel = InformationLevel.from_string(request.args.get('infolevel', ''), InformationLevel.AllInfo)
    include_debuginfo = (infolevel == InformationLevel.DebugInfo)
    with DatabaseAccess() as db:
        try:
            track = db.get_track_by_id(trackid)
        except NotFoundException:
            abort(HTTPStatus.NOT_FOUND, description=ERR_MSG_UNKNOWN_TRACK_ID)
        return gzippable_jsonify(json_track(track, include_debuginfo=include_debuginfo))
