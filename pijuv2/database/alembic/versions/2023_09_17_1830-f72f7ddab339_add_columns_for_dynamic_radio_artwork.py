"""
Add columns for dynamic radio artwork

Revision ID: f72f7ddab339
Revises: 2951dc400ac9
Create Date: 2023-09-17 18:30:29.298683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f72f7ddab339'
down_revision: Union[str, None] = '2951dc400ac9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('RadioStations', sa.Column('NowPlayingArtworkUrl', sa.String(), nullable=True))
    op.add_column('RadioStations', sa.Column('NowPlayingArtworkJq', sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('RadioStations', 'NowPlayingArtworkJq')
    op.drop_column('RadioStations', 'NowPlayingArtworkUrl')
    # ### end Alembic commands ###
