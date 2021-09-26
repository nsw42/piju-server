# pijuv2

## Development

```sh
python -m pijuv2.backend
```

## REST API

See <https://app.swaggerhub.com/apis/nwalker/piju/1.0#/>

## Dependencies

* [Flask](https://flask.palletsprojects.com)
* pexpect (4.8.0)
* Pillow

## Backlog

* Refactor/code tidy of the backend code
* Move `set_cross_refs` functionality into `ensure_track_exists` in database layer
* Bug fix: mpyg321 will sometimes crash with a pexpect EOF - seemingly if calls are made too frequently

### Done

* API: Implement `/tracks` for debugging
* API: Include the genre of an album in `/albums` and `/albums/<albumid>`
* API: Add `/genres` and `/genres/<genrename>` to return a list of albums
* API: Include the artwork URI in `/albums` and `/albums/<albumid>`
* API: Add `/artwork/<id>` and include artwork in `/tracks/<trackid>`
* API: Add image width/height to db, and include it in `/artworkinfo/<id>`
* API: Allow track information to be included when retrieving album
* API: Include album year to album json in the API
* Scan: Compute/store an artwork path for an album
* Scan: Compute/store the genres for an album
* Scan: Figure out why duplicate tracks are being created (partially fixed)
* Scan: Figure out where genres are being created with name 13 (etc)
* Scan: Bug fix: duplicate tracks are being created when re-scanning on a different day (dateutil.parser)
* Player: Add remote control of player to play album
* Player: Add ability to specify start index when starting an album
* Player: Add ability to play individual tracks
* Player: Add ability to pause/resume

## Credits

* `mpyg321.py` is based on <https://github.com/4br3mm0rd/mpyg321> (v1.4.1), with updates made to record the current track position,
  and also switched to Enum class.
