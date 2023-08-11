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

This step checks that all dependencies have installed successfully, and that
the PiJu server software has been installed and configured correctly. If any
errors happen here, fix them before trying to configure the piju-server
software to start automatically.

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

* Start the service:

    ```sh
    sudo /etc/init.d/piju start
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

Installing logrotate automatically causes it to run daily. It shouldn't be
necessary to perform any further configuration.

### Update the database

Before using the service for the first time, and any time that music is added
to the system, it's necessary to update the piju database.  See
<update_database.md>
