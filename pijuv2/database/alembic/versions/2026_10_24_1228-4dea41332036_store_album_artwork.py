"""
Store album artwork

Revision ID: 4dea41332036
Revises: d4317c0c11fa
Create Date: 2026-10-24 12:28:39.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4dea41332036'
down_revision: Union[str, None] = 'd4317c0c11fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('Albums', schema=None) as batch_op:
        batch_op.add_column(sa.Column('Artwork', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_Albums_Artwork_Artwork', 'Artwork', ['Artwork'], ['Id'])

    # Each album's artwork is that of its first track (in disk and track order) that has any:
    # a snapshot of Database.update_album_artwork
    albums_table = sa.table('Albums', sa.column('Id', sa.Integer), sa.column('Artwork', sa.Integer))
    tracks_table = sa.table('Tracks', sa.column('Id', sa.Integer), sa.column('Album', sa.Integer),
                            sa.column('Artwork', sa.Integer), sa.column('VolumeNumber', sa.Integer),
                            sa.column('TrackNumber', sa.Integer))
    first_artwork = (sa.select(tracks_table.c.Artwork)
                     .where(tracks_table.c.Album == albums_table.c.Id)
                     .where(tracks_table.c.Artwork.is_not(None))
                     .order_by(sa.func.coalesce(tracks_table.c.VolumeNumber, 0),
                               sa.func.coalesce(tracks_table.c.TrackNumber, 0),
                               tracks_table.c.Id)
                     .limit(1)
                     .scalar_subquery())
    op.get_bind().execute(albums_table.update().values(Artwork=first_artwork))


def downgrade() -> None:
    with op.batch_alter_table('Albums', schema=None) as batch_op:
        batch_op.drop_constraint('fk_Albums_Artwork_Artwork', type_='foreignkey')
        batch_op.drop_column('Artwork')
