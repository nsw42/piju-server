#! /bin/bash

albumid=$1
trackid=$2

if [ -z "$albumid" ]; then
  echo "Usage: $0 albumid  [trackid]"
  exit 1
fi


if [ -z "$trackid" ]; then
  curl -d '{"album": '$albumid'}' -H "Content-Type: application/json" http://localhost:5000/player/play
else
  curl -d '{"album": '$albumid', "track": '$trackid'}' -H "Content-Type: application/json" http://localhost:5000/player/play
fi
