# pylint: disable=redefined-outer-name,unused-argument
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pijuv2.backend import selfupdate
from pijuv2.backend.appfactory import create_app
from pijuv2.backend.selfupdate import install_and_restart, pull_latest, UpdateException
from pijuv2.backend.workrequests import WorkRequests


@pytest.fixture()
def test_app(tmp_path):
    app = create_app(config_file=None, db_path=tmp_path / 'test.db', create_db=True)
    app.config.update({
        'TESTING': True
    })
    yield app


@pytest.fixture()
def client(test_app):
    yield test_app.test_client()


def run_git(cwd: Path, *args: str) -> str:
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit_file(repo: Path, filename: str, content: str):
    (repo / filename).write_text(content)
    run_git(repo, 'add', filename)
    run_git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-q', '-m', filename)


@pytest.fixture()
def upstream_and_clone(tmp_path):
    """
    Create an upstream repo, and a clone of it that selfupdate is pointed at
    """
    upstream = tmp_path / 'upstream'
    upstream.mkdir()
    run_git(upstream, 'init', '-q', '-b', 'main')
    commit_file(upstream, 'run.sh', '#! /bin/sh\n')
    clone = tmp_path / 'clone'
    run_git(tmp_path, 'clone', '-q', str(upstream), str(clone))
    with patch.object(selfupdate, 'REPO_DIR', clone), patch.object(selfupdate, 'RUN_SCRIPT', clone / 'run.sh'):
        yield upstream, clone


# Route tests

def test_update_already_up_to_date(client, test_app):
    with patch('pijuv2.backend.routes.pull_latest', return_value=('a' * 40, 'a' * 40)):
        rsp = client.post('/update')
    assert rsp.status_code == 200
    assert rsp.json == {'updated': False, 'version': 'aaaaaaa'}
    assert test_app.work_queue.empty()


def test_update_queues_restart(client, test_app):
    with patch('pijuv2.backend.routes.pull_latest', return_value=('a' * 40, 'b' * 40)):
        rsp = client.post('/update')
    assert rsp.status_code == 202
    assert rsp.json == {'updated': True, 'from': 'aaaaaaa', 'to': 'bbbbbbb'}
    assert test_app.work_queue.get_nowait() == (WorkRequests.INSTALL_UPDATE_AND_RESTART, 'a' * 40, 'b' * 40)


def test_update_failure(client, test_app):
    with patch('pijuv2.backend.routes.pull_latest', side_effect=UpdateException('git pull --ff-only failed: oops')):
        rsp = client.post('/update')
    assert rsp.status_code == 500
    assert b'oops' in rsp.data
    assert test_app.work_queue.empty()


# pull_latest tests, against a real git repository

def test_pull_latest_no_change(upstream_and_clone):
    _, clone = upstream_and_clone
    head = run_git(clone, 'rev-parse', 'HEAD')
    assert pull_latest() == (head, head)


def test_pull_latest_with_change(upstream_and_clone):
    upstream, clone = upstream_and_clone
    old_head = run_git(clone, 'rev-parse', 'HEAD')
    commit_file(upstream, 'requirements.txt', 'Flask\n')
    new_head = run_git(upstream, 'rev-parse', 'HEAD')
    assert pull_latest() == (old_head, new_head)
    assert selfupdate.file_changed(old_head, new_head, 'requirements.txt')
    assert not selfupdate.file_changed(old_head, new_head, 'run.sh')


def test_pull_latest_refuses_divergence(upstream_and_clone):
    upstream, clone = upstream_and_clone
    commit_file(upstream, 'a.txt', 'upstream\n')
    commit_file(clone, 'b.txt', 'local\n')
    with pytest.raises(UpdateException):
        pull_latest()


def test_pull_latest_not_a_git_clone(tmp_path):
    (tmp_path / 'run.sh').write_text('#! /bin/sh\n')
    with patch.object(selfupdate, 'REPO_DIR', tmp_path), patch.object(selfupdate, 'RUN_SCRIPT', tmp_path / 'run.sh'):
        with pytest.raises(UpdateException, match='not running from a git clone'):
            pull_latest()


# install_and_restart tests

def make_app_mock():
    app = MagicMock()
    app.db_path = Path('/data/piju.db')
    app.config_file = Path('/home/piju/.pijudrc')
    app.file_player.control_thread.has_player.return_value = False
    return app


@pytest.mark.parametrize('requirements_changed', [True, False])
def test_install_and_restart(requirements_changed):
    app = make_app_mock()
    set_status = MagicMock()
    with patch.object(selfupdate, 'file_changed', return_value=requirements_changed), \
            patch.object(selfupdate, 'install_requirements') as mock_install, \
            patch.object(selfupdate.os, 'chdir'), \
            patch.object(selfupdate.os, 'execv') as mock_execv:
        install_and_restart(app, 'old', 'new', set_status)
    assert mock_install.called == requirements_changed
    app.file_player.stop.assert_called_once()
    app.stream_player.stop.assert_called_once()
    run_sh = str(selfupdate.RUN_SCRIPT)
    mock_execv.assert_called_once_with(run_sh, [run_sh, '-d', '/data/piju.db', '-c', '/home/piju/.pijudrc'])


def test_install_and_restart_pip_failure():
    app = make_app_mock()
    set_status = MagicMock()
    with patch.object(selfupdate, 'file_changed', return_value=True), \
            patch.object(selfupdate, 'install_requirements', side_effect=UpdateException('pip install failed')), \
            patch.object(selfupdate.os, 'execv') as mock_execv:
        install_and_restart(app, 'old', 'new', set_status)
    mock_execv.assert_not_called()
    set_status.assert_called_with('Update failed: pip install failed')
