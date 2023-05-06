# Deploying to a Raspberry Pi

## Environment

## Setting up the software

### Partitioning the SD Card

* Insert the SD card (via adapter) into MBP
* Figure out disk id (for me, it was `disk4`)
* `diskutil partitionDisk disk4 2 MBR "MS-DOS FAT32" ALPINE 1GB "MS-DOS FAT32" LINUX R`
* Download Raspberry Pi Alpine Linux from <https://dl-cdn.alpinelinux.org/alpine/v3.15/releases/armhf/alpine-rpi-3.15.0-armhf.tar.gz>
* `cd /Volumes/ALPINE; tar xvf ~/Downloads/alpine-rpi-3.15.0-armhf.tar.gz`
* Create usercfg.txt consisting of:

    ```text
    dtparam=audio=on
    display_rotate=2
    ```

* Unmount the SD card
* Put the SD card into the Pi, cable up the Pi and apply power

### Installing/configuring Alpine

* localhost login prompt: Username `root`, no password password
* If needed, fix up usercfg.txt (e.g. to set/remove `display_rotate=2`)
* Basically, follow <https://wiki.alpinelinux.org/wiki/Classic_install_or_sys_mode_on_Raspberry_Pi#Installation>
    * Format the second partition: `apk add e2fsprogs; mkfs.ext4 /dev/mmcblk0p2`
    * Run `setup-alpine` and work through the setup
    * Then do the various faff to get 'sys' mode working, which avoids the need to `lbu commit -d` all the time
* Check for OS updates: `apk update; apk  upgrade`

### Installing prerequisites for the music player

Logged in as root:

```sh
apk add mpg123
apk add alsa-utils
addgroup root audio
apk add py3-pillow
apk add git
apk add python3
wget https://bootstrap.pypa.io/get-pip.py -O get-pip.py
python3 get-pip.py
# If it's something you'll use:
apk add rsync
```

(Attempts to `pip install` Pillow results in it trying to build from source)

### Installing prerequisites for the touchscreen UI

Logged in as root:

* `setup-xorg-base`
* `apk add mesa-dri-vc4 mesa-dri-swrast mesa-gbm xf86-video-fbdev xfce4 xfce4-terminal`
* `apk add xset py3-gobject3`
* Edit /media/mmcblk0p1/usercfg.txt, to add:

    ```text
    lcd_rotate=2
    dtoverlay=vc4-fkms-v3d
    gpu_mem=256
    ```

    * `lcd_rotate=2` seems to be needed instead of `display_rotate=2` after installing X and these drivers

* Create `/etc/X11/xorg.conf`:

    ```text
    Section "Device"
      Identifier "default"
      Driver "fbdev"
    EndSection
    ```

### Installing prerequisites for playing tracks from YouTube

Logged in as root:

```
wget https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -O /usr/local/bin/yt-dlp
chmod a+rx /usr/local/bin/yt-dlp
apk add ffmpeg
```

### Create a user to run the software

Logged in as root:

```sh
adduser piju
addgroup piju wheel  # for sudo
addgroup piju audio,tty,input,video  # input and video needed for X, i.e. for the touchscreen UI
```

### Python packages

Logged in as piju:

```sh
git clone https://github.com/nsw42/piju-server.git
cd piju-server
pip install -r requirements.txt
```

### Import music

Logged in as piju:

```sh
mkdir music
scp -r <SOMEWHERE> .
```

Obviously, it's up to you to figure out where your music is coming from. Or,
you may choose to scp/rsync *to* piju. Either way, now's a good time to get a
drink: transferring your music library to the Pi will probably take a while.

### Create a configuration file

Logged in as piju, create a file `~/.pijudrc` that looks something like this:

```json
{
    "music_dir": "/home/piju/music"
}
```

### Start the server (as a one-off; not yet configured to auto-start)

Logged in as piju:

```sh
cd piju-server
python3 -m pijuv2.backend
```

Ctrl-C to exit

### Configure the server to start automatically

* scp init.d/piju to /etc/init.d/piju
* Make the script executable:

    ```sh
    sudo chown root:root /etc/init.d/piju
    sudo chmod 755 /etc/init.d/piju
    ```

* Create relevant log directory and add it as a service:

    ```sh
    sudo mkdir /var/log/piju
    sudo chmod 777 /var/log/piju
    sudo rc-update add piju default
    ```

### Set up log rotation

Install logrotate:

```sh
apk add logrotate
```

Write a logrotate configuration file (`/etc/logrotate.d/piju`):

```text
/var/log/piju/piju.log
/var/log/piju/piju.err
{
    su piju piju
    daily
    missingok
    notifempty
    compress
    copytruncate
}
```

Installing logrotate automatically causes it to run daily. Shouldn't be any further configuration needed.
