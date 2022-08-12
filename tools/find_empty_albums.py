import sqlite3
import sys

db = sys.argv[1]
con = sqlite3.connect(db)
cur = con.execute('SELECT * FROM Albums WHERE NOT (EXISTS (SELECT 1 FROM Tracks WHERE Albums.Id = Tracks.Album))')
rows = cur.fetchall()
for row in rows:
    print(row)
