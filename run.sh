#! /bin/sh

SCRIPT_DIR=$(realpath $(dirname $0))

function usage() {
  echo "Usage: $0 [OPTIONS] DBFILE"
  echo "Options:"
  echo "  -C         Create DBFILE as a new database"
  echo "  -c  FILE   Use FILE as a config file"
  exit 1
}

create=false
CONFIG_FILE=
DB_FILE=

while getopts :Cc:d: arg; do
  case $arg in
    C)
      create=true
      ;;
    c)
      CONFIG_FILE=$OPTARG
      ;;
    d)
      DB_FILE=$OPTARG
      ;;
    ?)
      usage
      ;;
  esac
done

shift $(( OPTIND - 1 ))

if [ -z "$DB_FILE" ]; then
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
fi

if [ ! -f "$DB_FILE" ]; then
  $create || {
    echo "File '$DB_FILE' does not exist. Use the -C option to create it"
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

if [ "$CONFIG_FILE" ]; then
  exec $PYTHON -m pijuv2.backend -d "$DB_FILE" -c "$CONFIG_FILE"
else
  exec $PYTHON -m pijuv2.backend -d "$DB_FILE"
fi
