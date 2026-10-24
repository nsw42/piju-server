"""
Update the server to the latest version from its git upstream, and restart it.

The server is deployed as a git clone (see doc/deploy.md), so updating is:
  1. `git pull --ff-only` from the upstream of the current branch (done synchronously by the
     route handler, so that the client gets to hear about failures)
  2. `pip install -r requirements.txt`, if requirements.txt changed
  3. re-exec `run.sh`, which applies any database migrations before starting the server.
     Re-exec keeps the same PID, so the init system's pidfile remains valid.
"""
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

REPO_DIR = Path(__file__).resolve().parents[2]
RUN_SCRIPT = REPO_DIR / 'run.sh'
REQUIREMENTS_FILE = 'requirements.txt'
PLAYER_STOP_TIMEOUT = 5  # seconds


class UpdateException(Exception):
    """
    Exception thrown if the update cannot be performed
    """


def can_update() -> str | None:
    """
    Return None if it looks like an update can be attempted, or a string describing why not
    """
    if not (REPO_DIR / '.git').is_dir():
        return "Server is not running from a git clone"
    if not RUN_SCRIPT.is_file():
        return f"{RUN_SCRIPT} not found"
    return None


def git(*args: str) -> str:
    child = subprocess.run(['git', *args], cwd=REPO_DIR, capture_output=True, text=True, check=False)
    if child.returncode != 0:
        raise UpdateException(f"git {' '.join(args)} failed: {child.stderr.strip()}")
    return child.stdout.strip()


def pull_latest() -> tuple[str, str]:
    """
    Pull the latest changes from upstream. Returns the (old, new) commit hashes
    """
    reason = can_update()
    if reason:
        raise UpdateException(reason)
    old_head = git('rev-parse', 'HEAD')
    git('pull', '--ff-only')
    new_head = git('rev-parse', 'HEAD')
    return old_head, new_head


def file_changed(old_head: str, new_head: str, filename: str) -> bool:
    return git('diff', '--name-only', old_head, new_head, '--', filename) != ''


def install_requirements():
    child = subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', REQUIREMENTS_FILE],
                           cwd=REPO_DIR, capture_output=True, text=True, check=False)
    if child.returncode != 0:
        raise UpdateException(f"pip install failed: {child.stderr.strip()}")


def stop_players(app):
    """
    Stop any playback, so that player subprocesses don't outlive the restart
    """
    app.stream_player.stop()
    app.file_player.stop()
    # FilePlayer.stop() is asynchronous: wait for the control thread to act on it
    deadline = time.monotonic() + PLAYER_STOP_TIMEOUT
    while app.file_player.control_thread.has_player() and time.monotonic() < deadline:
        time.sleep(0.1)


def restart(app):
    args = [str(RUN_SCRIPT), '-d', str(app.db_path)]
    if app.config_file:
        args += ['-c', str(app.config_file)]
    logging.info(f"Restarting: {' '.join(args)}")
    stop_players(app)
    sys.stdout.flush()
    sys.stderr.flush()
    os.chdir(REPO_DIR)
    os.execv(args[0], args)


def install_and_restart(app, old_head: str, new_head: str, set_status: Callable[[str], None]):
    """
    Having pulled from old_head to new_head, install any changed dependencies and restart.
    Runs on the worker thread. Errors are logged and reported via set_status; they do not propagate.
    """
    try:
        if file_changed(old_head, new_head, REQUIREMENTS_FILE):
            set_status('Updating: installing dependencies')
            install_requirements()
        set_status('Updating: restarting')
        restart(app)
    except (UpdateException, OSError) as exc:
        logging.error(f"Update failed: {exc}")
        set_status(f'Update failed: {exc}')
