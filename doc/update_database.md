# Updating the database

After you install the software, and any time you add new music to PiJu, it is
necessary to scan the music and update the piju database.

This currently requires a command-line command to send a message to the server;
there is not yet a user interface available for this.

From a Windows machine running WSL, a Mac, or a Linux machine (including the
Raspberry Pi that's running piju):

```sh
curl -X POST -H "Content-Type: application/json" -d '{"dir": "SUBDIR"}}' "http://PIJUADDRESS:5000/scanner/scan"
```

Replace PIJUADDRESS with the hostname or IP address of the piju server (or
`localhost` if you're running the command on that computer), and replace SUBDIR
in the message body with the sub-directory of the pju music folder you want to
scan. To scan the entire music collection, which may take a while, set SUBDIR
to `.`

Also see <https://github.com/nsw42/piju-bash-client>, which provides some
utility shell functions, and contains a utility script `scan_dir.sh`: running
that requires less typing than the curl command.

Alternatively, you can use <https://www.postman.com> Postman to send the
message.
