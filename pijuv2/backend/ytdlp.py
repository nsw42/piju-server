from collections import namedtuple
import json
from pathlib import Path
import subprocess


DownloadInfo = namedtuple('DownloadInfo', 'filepath, artist, title')
# filepath: Path
# artist: str
# title: str


def fetch_audio(url, download_dir):
    cmd = ['yt-dlp',
           '-x',
           '--audio-format', 'mp3',
           '-f', 'ba',
           '--no-download-archive',
           url,
           '-o', '%(id)s.%(ext)s',
           '--print', 'after_move:filepath',
           '--write-info-json']
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=download_dir)
    local_files = result.stdout.splitlines()
    download_info = []
    for local_file in local_files:
        filepath = Path(local_file)
        metadata_path = filepath.with_suffix('.info.json')
        with open(metadata_path) as handle:
            metadata = json.load(handle)
            artist = metadata.get('artist')
            title = metadata.get('title')
        download_info.append(DownloadInfo(filepath, artist, title))
    return download_info
