from argparse import ArgumentParser
from itertools import chain

import requests


class GenreCache:
    def __init__(self, host):
        self.host = host
        self.genres = {}
    def __getitem__(self, genre):
        if genre not in self.genres:
            uri = f'{self.host}genres/{genre}'
            response = requests.get(uri)
            if not response.ok:
                raise Exception(f'Genre {genre} not found')
            self.genres[genre] = response.json()['name']
        return self.genres[genre]


def parse_args():
    parser = ArgumentParser()
    parser.add_argument('--host', help="base host URI, eg %(default)s")
    parser.add_argument('artist')
    parser.set_defaults(host='http://localhost:5000/')
    args = parser.parse_args()
    if not args.host.endswith('/'):
        args.host += '/'
    return args


def query(host, artist):
    uri = f'{host}artists/{artist}?tracks=all'
    response = requests.get(uri)
    if not response.ok:
        print("Could not find artist")
        return
    return response.json()[artist]


def format_artist(host, artist_info):
    genres = GenreCache(host)
    table = []
    for album in artist_info:
        row = [album['title'], '', '']
        table.append(row)
        for track in album['tracks']:
            row = ['', track['title'], genres[track['genre']]]
            table.append(row)
    return table


def main():
    args = parse_args()
    artist_info = query(args.host, args.artist)
    if not artist_info:
        return
    table = format_artist(args.host, artist_info)
    if not table:
        return
    nr_columns = len(table[0])
    col_widths = [2+max([len(row[c]) for row in table]) for c in range(nr_columns)]
    for row in table:
        print(('%-*s' * nr_columns) % tuple(chain(*zip(col_widths, row))))


if __name__ == '__main__':
    main()
