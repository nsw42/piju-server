# Deploying a Satellite

## Introduction

A satellite Piju server is a server that provides the API that the webui requires,
but which acts as a remote to a central server that contains the database, referred
to as the "primary". Many API requests (e.g. database searches) simply get redirected
to the central server, so the satellite and the primary need to both be available
on the network, but commands to play music will cause the satellite to start
playing. Similarly, requests to add items to the queue will be added to the
satellite's queue, rather than the primary's.

## Deploying to Ubuntu

Other Linuxes will be similar, but the steps here give an indication of what is
required to get the satellite working. This has only been tested in a Docker
image, so there may be unexpected gaps.

```sh
apt-get update
apt-get install -y git mpg123 python3 python3.12-venv
git clone https://github.com/nsw42/piju-server.git
cd piju-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m pijuv2.satellite $PRIMARY
```

replacing `$PRIMARY` with the IP address or hostname of your primary Piju server.

## Deploying to Windows

Untested, but should be largely similar, if you're able to use git-bash.

## Running the webui

See [webui docs](https://github.com/nsw42/piju-webui/blob/main/doc/deploy.md)
for more detail, but basically grab the source, run it and point it at
localhost:5000 (i.e. your satellite, not your primary) and then point
a browser at localhost:80.
