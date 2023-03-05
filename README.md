# pijuv2

## Development

```sh
python -m pijuv2.backend
```

## REST API

See <https://app.swaggerhub.com/apis/nwalker/piju/1.0#/>

## Dependencies

* [Flask](https://flask.palletsprojects.com)
* mutagen
* pexpect (4.8.0)
* Pillow
* SQLAlchemy

## Backlog

* Detect files being deleted
* Bug fix: Too many open files under heavy load
* Bug fix: Scanner is finding a lot of tracks without a title
* Include album disk number to album json in the API
* Refactor/code tidy of the backend code
* Tech debt: Move `set_cross_refs` functionality into `ensure_track_exists` in database layer
* Include track length in /tracks/NNN response
* Add more API endpoints to allow querying the database (e.g. by artist)

### Done

* API: Implement `/tracks` for debugging
* API: Include the genre of an album in `/albums` and `/albums/<albumid>`
* API: Add `/genres` and `/genres/<genrename>` to return a list of albums
* API: Include the artwork URI in `/albums` and `/albums/<albumid>`
* API: Add `/artwork/<id>` and include artwork in `/tracks/<trackid>`
* API: Add image width/height to db, and include it in `/artworkinfo/<id>`
* API: Allow track information to be included when retrieving album
* API: Include album year to album json in the API
* API: (Tech debt) use jsonify or just return a dict, return than json.dumps
* API/Database bug fix: `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread. The object was created in thread id 6117453824 and this is thread id 6151106560.` when accessing `/tracks` for the first time after scanning has finished.
* Scan: Compute/store an artwork path for an album
* Scan: Compute/store the genres for an album
* Scan: Figure out why duplicate tracks are being created (partially fixed)
* Scan: Figure out where genres are being created with name 13 (etc)
* Scan: Bug fix: duplicate tracks are being created when re-scanning on a different day (dateutil.parser)
* Scan: Bug fix: Cyberpunk 2077 OST is showing as multiple separate albums
* Player: Add remote control of player to play album
* Player: Add ability to specify start index when starting an album
* Player: Add ability to play individual tracks
* Player: Add ability to pause/resume
* Player: Add ability to control volume
* Replica: First version: provide the same /player/ API as the full backend, but cache audio data from a primary backend
* Bug fix: mpyg321 will sometimes crash with a pexpect EOF - seemingly if calls are made too frequently. (Fixed as a side effect of adding MP4 support: each new track gets a new player instance)
* Bug fix: sometimes ending up with multiple Track entries for a single filepath
* Bug fix: Better error handling if attempting to play a missing file
* Bug fix: Changing an album's artist (eg from a compilation to a single artist) was leaving an empty album

## Credits

* `mpyg321.py` is based on <https://github.com/4br3mm0rd/mpyg321> (v1.4.1), with updates made to record the current track position,
  and also switched to Enum class.
