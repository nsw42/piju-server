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
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True,
                                cwd=download_dir)
    except subprocess.CalledProcessError:
        return
    local_file = result.stdout.strip()
    return local_file
