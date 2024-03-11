import logging

from flask_socketio import emit

from .nowplaying import get_current_status


def on_ws_connect():
    logging.info('New websocket connection')
    data = get_current_status()
    emit('now_playing_update', data)


def broadcast_now_playing_update(socketio):
    data = get_current_status()
    socketio.emit('now_playing_update', data)
