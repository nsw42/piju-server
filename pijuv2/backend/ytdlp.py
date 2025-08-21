import json
import logging
from pathlib import Path
import subprocess

from flask import current_app

from .downloadinfo import DownloadInfo, DownloadInfoDatabaseSingleton


def select_thumbnail(thumbnails):
    best_thumbnail = None
    for thumbnail in thumbnails:
        if thumbnail.get('url', '').endswith('.jpg') \
                and (best_thumbnail is None or thumbnail.get('preference') > best_thumbnail.get('preference')):
            best_thumbnail = thumbnail
    return best_thumbnail['url'] if best_thumbnail else None


def fetch_audio(url, download_dir) -> list[DownloadInfo]:
    cmd = ['yt-dlp',
           '--ignore-config',
           '-x',
           '-f', 'ba',
           '--no-download-archive',
           url,
           '-o', '%(id)s.%(ext)s',
           '--print', 'after_move:filepath',
           '--write-info-json']
    if current_app.piju_config.cookies_file:
        cmd += ['--cookies', current_app.piju_config.cookies_file]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=download_dir)
    except subprocess.CalledProcessError as ex:
        logging.debug('ytdlp failed:\nstdout:%s\nstderr:%s\n', ex.stdout, ex.stderr)
        return []
    local_files = result.stdout.splitlines()
    all_download_info = []
    for local_file in local_files:
        filepath = Path(local_file)
        metadata_path = filepath.with_suffix('.info.json')
        with open(metadata_path, encoding='utf-8') as handle:
            metadata = json.load(handle)
            artist = metadata.get('artist')
            title = metadata.get('title')
            artwork = select_thumbnail(metadata.get('thumbnails'))
            url = metadata.get('webpage_url')
        fake_trackid = DownloadInfoDatabaseSingleton().get_id_for_filepath(filepath)
        one_download_info = DownloadInfo(filepath, artist, title, artwork, url, fake_trackid)
        all_download_info.append(one_download_info)
        DownloadInfoDatabaseSingleton().add_download_info(fake_trackid, one_download_info)
    return all_download_info
