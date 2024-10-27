#! /bin/sh

echo "About to run sudo. You may be prompted to enter a password."

sudo install -m 755 init.d/piju-server /etc/init.d/
sudo install -m 644 logrotate.d/piju /etc/logrotate.d/
sudo mkdir /var/log/piju-server
sudo chmod 777 /var/log/piju-server
sudo rc-update add piju-server default
