import json
from pathlib import Path
from typing import Iterable
import subprocess

from .downloadinfo import DownloadInfo


def select_thumbnail(thumbnails):
    best_thumbnail = None
    for thumbnail in thumbnails:
        if thumbnail.get('url', '').endswith('.jpg') \
                and (best_thumbnail is None or thumbnail.get('preference') > best_thumbnail.get('preference')):
            best_thumbnail = thumbnail
    return best_thumbnail['url'] if best_thumbnail else None


def fetch_audio(url, download_dir) -> Iterable[DownloadInfo]:
    cmd = ['yt-dlp',
           '-x',
           '--audio-format', 'mp3',
           '-f', 'ba',
           '--no-download-archive',
           url,
           '-o', '%(id)s.%(ext)s',
           '--print', 'after_move:filepath',
           '--write-info-json']
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=download_dir)
    except subprocess.CalledProcessError:
        return []
    local_files = result.stdout.splitlines()
    download_info = []
    for local_file in local_files:
        filepath = Path(local_file)
        metadata_path = filepath.with_suffix('.info.json')
        with open(metadata_path) as handle:
            metadata = json.load(handle)
            artist = metadata.get('artist')
            title = metadata.get('title')
            artwork = select_thumbnail(metadata.get('thumbnails'))
            url = metadata.get('webpage_url')
        download_info.append(DownloadInfo(filepath, artist, title, artwork, url))
    return download_info
