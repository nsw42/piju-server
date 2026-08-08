"""
Session storage for browser-mode queue playback.

Browser-based playback needs to track a small amount of per-client state (the
queue contents) without a signed cookie session: a cross-origin cookie needs
SameSite=None, and browsers additionally require SameSite=None cookies to be
Secure, which they silently refuse to store for a plain-HTTP, non-localhost
origin - the normal case for a piju server reached over the LAN. Rather than
requiring TLS, the client instead generates its own opaque session id and
sends it on every request via the X-Piju-Queue-Session header; the server
just uses it as a lookup key into an in-memory cache. This isn't
authentication, just a namespace to keep different browsers' queues apart, so
it carries none of the cookie SameSite/Secure baggage.

/queue/ws is the one exception: a WebSocket handshake can't carry custom
headers, so that endpoint's client instead passes the session id via a
`session` query param.
"""
from cachelib.simple import SimpleCache
from flask import Request
from werkzeug.exceptions import BadRequest

QUEUE_SESSION_HEADER = 'X-Piju-Queue-Session'
QUEUE_SESSION_QUERY_ARG = 'session'

_TIMEOUT_SECONDS = 60 * 60 * 24  # expire an abandoned queue after a day
_cache = SimpleCache(threshold=500, default_timeout=_TIMEOUT_SECONDS)


def _session_id(request: Request) -> str:
    session_id = request.headers.get(QUEUE_SESSION_HEADER) or request.args.get(QUEUE_SESSION_QUERY_ARG)
    if not session_id:
        raise BadRequest(f"{QUEUE_SESSION_HEADER} header is required for browser-mode queue operations")
    return session_id


def get_browser_queue(request: Request) -> list[int]:
    return _cache.get(_session_id(request)) or []


def set_browser_queue(request: Request, queue: list[int]):
    _cache.set(_session_id(request), queue)
