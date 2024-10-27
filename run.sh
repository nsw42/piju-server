#! /bin/sh

SCRIPT_DIR=$(realpath $(dirname $0))

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

if [ "$1" ]; then
  DB_FILE=$1
else
  for f in "$SCRIPT_DIR/piju.db" "$SCRIPT_DIR/file.db"; do
    if [ -f "$f" ]; then
      DB_FILE=$f
      break
    fi
  done
fi

if [ -z "$DB_FILE" ]; then usage; fi

if [ ! -f "$DB_FILE" ]; then
  $create || {
    echo "File '$DB_FILE' does not exist. Use the -c option to create it"
    exit 1
  }
  touch "$DB_FILE"
fi

DB_FILE=`realpath "$DB_FILE"`

# Check for alembic
ALEMBIC=$(command -v alembic)
if [ -z "$ALEMBIC" ]; then
  # Try in the default installation
  ALEMBIC=$HOME/.local/bin/alembic
  if [ ! -x "$ALEMBIC" ]; then
    echo alembic not found. Aborting.
    exit 1
  fi
fi

# Update database schema as necessary
export DB_FILE
cd $SCRIPT_DIR/pijuv2/database
$ALEMBIC current 2> /dev/null | grep -q head && { echo Database schema is up-to-date; } || {
  BACKUP=${DB_FILE}.bak
  echo "Updating database file: keeping a backup as $BACKUP"
  cp -pf "$DB_FILE" "$BACKUP"
  $ALEMBIC upgrade head || { echo Database upgrade failed. Aborting.; exit 1; }
}
cd $SCRIPT_DIR

# Now run the server
if [ -x $SCRIPT_DIR/bin/python3 ]; then
  PYTHON=$SCRIPT_DIR/bin/python3
else
  # let's hope $PATH is set
  PYTHON=python3
fi

exec $PYTHON -m pijuv2.backend -d "$DB_FILE"
