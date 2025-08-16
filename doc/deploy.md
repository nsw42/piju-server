# Deploying to a Raspberry Pi

This page describes getting the software installed and running; it does not
describe important steps such as adding music. For the full context of getting
a working music player, see the step-by-step instructions at
<https://github.com/nsw42/piju-docs/README.md>

These instructions assume you are deploying on top of an OS installed and
configured as per
<https://github.com/nsw42/piju-docs/install_hardware_and_os.md>.

## Fetch the PiJu server software and install Python dependencies

Installing from git is currently the only supported option; released binaries
may happen eventually.

Logged in as piju:

```sh
git clone https://github.com/nsw42/piju-server.git
cd piju-server
python3 -m venv --system-site-packages .
. bin/activate
pip install -r requirements.txt
```

### Create a configuration file

Logged in as piju, create a file `~/.pijudrc` that looks something like this:

```json
{
    "music_dir": "/home/piju/music"
}
```

The path you point at depends on the directory you created earlier in the
process. The `/home/piju/music` value is used throughout all these
instructions.

### Start the server (as a one-off; not yet configured to auto-start)

This step checks that all dependencies have installed successfully, that the
PiJu server software has been installed and configured correctly, and also
creates an empty database (using the filename that's assumed in the init.d
service script).

If any errors happen here, fix them before trying to configure the piju-server
software to start automatically.

Logged in as piju:

```sh
cd piju-server
./run.sh -C file.db
```

Ctrl-C to exit

### Configure the server to start automatically and rotate logs

- Logged in as piju, add the service and set up log rotation:

  ```sh
  cd piju-server/deploy/
  ./install.sh
  ```

- Start the service and check it started successfully:

  ```sh
  sudo /etc/init.d/piju-server start
  sudo /etc/init.d/piju-server status
  ```

- Check the log files as necessary:

  ```sh
  less /var/log/piju-server/piju-server.err
  less /var/log/piju-server/piju-server.log
  ```

(Note that the logrotate configuration file also sets up log rotation for the touchscreen
and webui piju components, on the assumption that you're going to install them. The file
contains a `missingok` line that means that it's not a problem if you choose not to run
them.)

Installing logrotate automatically causes it to run daily. It shouldn't be
necessary to perform any further configuration.

### Update the database

Before using the service for the first time, and any time that music is added
to the system, it's necessary to update the piju database.  See
[update_database.md](update_database.md).

### Use cookies to authenticate YouTube downloads

YouTube blocks attempts to download audio for some videos unless the request
is authenticated by a user account. To do this, you will need to use the
yt-dlp cookie support:

- (recommended but not essential) create a dedicated YouTube account, in case YouTube
  blocks your account
- follow the
  [yt-dlp instructions](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies)
  to save the cookies for that account to a cookies.txt file
- copy that cookies.txt file to your Pi
- update your piju configuration file:

  ```json
  {
    "cookies": "/path/to/cookies.txt",
    ...
  }
  ```

- restart piju, to get it to reload your configuration file
