import subprocess


def fetch_audio(url, download_dir):
    cmd = ['yt-dlp',
           '-x',
           '--audio-format', 'mp3',
           '-f', 'ba',
           '--no-download-archive',
           url,
           '-o', '%(id)s.%(ext)s',
           '--print', 'after_move:filepath']
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=download_dir)
    local_files = result.stdout.splitlines()
    return local_files
