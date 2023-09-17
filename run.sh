#! /bin/bash

function usage() {
  echo "Usage: $0 [OPTIONS] DBFILE"
  echo "Options:"
  echo "  -c   Create DBFILE as a new database"
  exit 1
}

create=false

while getopts :c arg; do
  case $arg in
    c)
      create=true
      ;;
    ?)
      usage
      ;;
  esac
done

shift $(( OPTIND - 1 ))
DB_FILE=$1

if [ -z "$DB_FILE" ]; then usage; fi

if [ ! -f "$DB_FILE" ]; then
  $create || {
    echo "File '$DB_FILE' does not exist. Use the -c option to create it"
    exit 1
  }
  touch "$DB_FILE"
fi

DB_FILE=`realpath "$DB_FILE"`

# Update database schema as necessary
export DB_FILE
pushd pijuv2/database >& /dev/null
alembic current 2> /dev/null | grep -q head && { echo Database scehma is up-to-date; } || {
  BACKUP=${DB_FILE}.bak
  echo "Updating database file: keeping a backup as $BACKUP"
  cp -pf "$DB_FILE" "$BACKUP"
  alembic upgrade head || { echo Database upgrade failed. Aborting.; exit 1; }
}
popd >& /dev/null

# Now run the server
python3 -m pijuv2.backend -d "$DB_FILE"
