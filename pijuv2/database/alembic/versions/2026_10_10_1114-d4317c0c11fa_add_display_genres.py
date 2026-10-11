"""
Add display genres

Revision ID: d4317c0c11fa
Revises: 8d53a02d7bb6
Create Date: 2026-10-10 11:14:27.458790

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4317c0c11fa'
down_revision: Union[str, None] = '8d53a02d7bb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DEFAULT_DISPLAY_GENRE_NAME = "Uncategorised"

# The grouping of genres into display genres, as it was in the web UI at the point
# that it moved into the database. This is the initial content only: once this
# migration has been run, the database is the source of truth.
# (display genre name, icon, view style, [genre names])
INITIAL_DISPLAY_GENRES = [
    ("Comedy", "music", "albums", [
        "Comedy",
        "Humour",
    ]),
    ("Electronic", "music", "albums", [
        "Electronic",
        "Electronica",
        "Experimental Electronic",
    ]),
    ("Jazz, Blues & Soul", "music", "albums", [
        "Blues",
        "Bluegrass",
        "Funk",
        "Funk Soul",
        "Jazz",
        "Ragtime",
        "R&B",
        "Soul",
    ]),
    ("Rock & Pop", "music", "albums", [
        "Acoustic Rock",
        "Alt. Rock",
        "Alternative",
        "Alternative Indie",
        "Alternative Pop Rock",
        "Alternative Rock",
        "AOR Classic Rock",
        "Art Rock",
        "Avant Garde",
        "Avantgarde",
        "Big Beat",
        "Britpop",
        "BritPop",
        "Celtic",
        "Classic Rock",
        "Children's",
        "Contemporary Pop",
        "Coldwave Synth",
        "Dance",
        "Dance & DJ",
        "Dance & House",
        "Disco",
        "Downtempo",
        "Electro swing",
        "Electroswing",
        "Garage",
        "Garage Rock Revival",
        "General Metal",
        "General Rock",
        "Glam Rock",
        "Hard Rock",
        "Hard Rock & Metal",
        "Heavy Metal",
        "Hip Hop",
        "House",
        "Indie",
        "Indie Alternative",
        "Indie Rock",
        "Jazz Rock",
        "Metal",
        "Miscellaneous",
        "New Age",
        "New Wave",
        "Nu Metal",
        "Oldies",
        "Other",
        "Pop",
        "Pop Rock",
        "Post rock",
        "Pre Punk",
        "Progressive Metal",
        "Punk",
        "Rap",
        "Reggae",
        "Rock",
        "Rock Pop",
        "Rock & Roll",
        "Ska",
        "Ska Reggae",
        "Synthpop",
    ]),
    ("Folk & Country", "music", "albums", [
        "Contemporary Country",
        "Country",
        "Country & Folk",
        "Folk",
        "Folk Rock",
    ]),
    ("Goth & Industrial", "music", "albums", [
        "Darkwave",
        "Gothic Rock",
        "Industrial",
        "Post Punk",
    ]),
    ("Ambient", "music", "albums", [
        "Ambient",
        "Dark Ambient",
        "Meditative",
    ]),
    ("Lounge", "music", "albums", [
        "Easy Listening",
    ]),
    ("World", "music", "albums", [
        "International",
        "Latin",
        "(Latin)",
        "Latin Music",
        "Traditional",
        "World",
        "(World)",
    ]),
    ("Soundtrack", "music", "albums", [
        "OST",
        "Soundtrack",
        "Soundtracks",
    ]),
    ("Classical", "music", "albums", [
        "Classical",
        "General Classical",
        "Modern Classical",
        "Religious",
    ]),
    ("Educational", "music", "albums", [
        "Education",
        "Educational",
    ]),
    ("Uncategorised", "music", "albums", [
    ]),
    ("Spoken word", "spoken_word", "artists", [
        "Speech",
        "Spoken & Audio",
        "Spoken Word",
    ]),
]


def normalize_genre_name(genre_name: str) -> str:
    # A snapshot of pijuv2.database.displaygenre.normalize_genre_name
    genre_name = genre_name.casefold()
    genre_name = re.sub(r'[/-]', ' ', genre_name)
    genre_name = re.sub(r'[()]', '', genre_name)
    genre_name = re.sub(r'  +', ' ', genre_name)
    return genre_name.strip()


def upgrade() -> None:
    display_genres_table = op.create_table(
        'DisplayGenres',
        sa.Column('Id', sa.Integer(), nullable=False),
        sa.Column('Name', sa.String(), nullable=True),
        sa.Column('Icon', sa.String(), nullable=True),
        sa.Column('ViewStyle', sa.String(), nullable=True),
        sa.Column('SortOrder', sa.Integer(), nullable=True),
        sa.Column('IsDefault', sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint('Id')
    )
    mappings_table = op.create_table(
        'DisplayGenreMappings',
        sa.Column('GenreName', sa.String(), nullable=False),
        sa.Column('DisplayGenreId', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['DisplayGenreId'], ['DisplayGenres.Id'], ),
        sa.PrimaryKeyConstraint('GenreName')
    )
    with op.batch_alter_table('Genres', schema=None) as batch_op:
        batch_op.add_column(sa.Column('DisplayGenreId', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_Genres_DisplayGenreId'), ['DisplayGenreId'], unique=False)
        batch_op.create_foreign_key('fk_Genres_DisplayGenreId_DisplayGenres', 'DisplayGenres',
                                    ['DisplayGenreId'], ['Id'])

    # Populate the new tables
    display_genres = []
    mappings = {}  # normalized genre name -> display genre id
    default_display_genre_id = None
    for index, (name, icon, view_style, genre_names) in enumerate(INITIAL_DISPLAY_GENRES):
        display_genre_id = index + 1
        is_default = (name == DEFAULT_DISPLAY_GENRE_NAME)
        if is_default:
            default_display_genre_id = display_genre_id
        display_genres.append({'Id': display_genre_id, 'Name': name, 'Icon': icon, 'ViewStyle': view_style,
                               'SortOrder': index, 'IsDefault': is_default})
        for genre_name in genre_names:
            mappings[normalize_genre_name(genre_name)] = display_genre_id
    op.bulk_insert(display_genres_table, display_genres)
    op.bulk_insert(mappings_table, [{'GenreName': genre_name, 'DisplayGenreId': display_genre_id}
                                    for genre_name, display_genre_id in mappings.items()])

    # Assign every existing genre to a display genre
    genres_table = sa.table('Genres', sa.column('Id', sa.Integer), sa.column('Name', sa.String),
                            sa.column('DisplayGenreId', sa.Integer))
    connection = op.get_bind()
    for genre_id, genre_name in connection.execute(sa.select(genres_table.c.Id, genres_table.c.Name)).fetchall():
        display_genre_id = mappings.get(normalize_genre_name(genre_name or ''), default_display_genre_id)
        connection.execute(genres_table.update()
                           .where(genres_table.c.Id == genre_id)
                           .values(DisplayGenreId=display_genre_id))


def downgrade() -> None:
    with op.batch_alter_table('Genres', schema=None) as batch_op:
        batch_op.drop_constraint('fk_Genres_DisplayGenreId_DisplayGenres', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_Genres_DisplayGenreId'))
        batch_op.drop_column('DisplayGenreId')

    op.drop_table('DisplayGenreMappings')
    op.drop_table('DisplayGenres')
