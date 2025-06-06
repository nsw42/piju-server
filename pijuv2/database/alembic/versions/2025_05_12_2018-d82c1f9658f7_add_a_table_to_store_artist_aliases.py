"""
Add a table to store artist aliases

Revision ID: d82c1f9658f7
Revises: 1abb628b0b5b
Create Date: 2025-05-12 20:18:21.327950

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd82c1f9658f7'
down_revision: Union[str, None] = '1abb628b0b5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('ArtistAliases',
    sa.Column('Artist', sa.String(), nullable=False),
    sa.Column('_AlternativeNames', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('Artist')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('ArtistAliases')
    # ### end Alembic commands ###
