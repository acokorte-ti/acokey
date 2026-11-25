"""ordem dos anexos: posição escolhida pelo usuário para cada documento da etapa (vale no databook)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-25 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Vazia = ninguém escolheu a ordem: vale a alfabética do nome do arquivo, como no sistema antigo
    op.add_column('anexos', sa.Column('ordem', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('anexos', 'ordem')
