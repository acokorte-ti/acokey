"""ops do mega: origem da OP, situação no Mega, última busca e o retrato do Mega (pedido, notas de saída)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-24 13:00:17.025910
"""
from alembic import op
import sqlalchemy as sa

import app.tipos  # noqa: F401  (tipos próprios: DataHoraFuso)
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ordens_producao', sa.Column('origem', sa.String(length=10), server_default='manual', nullable=False))
    op.add_column('ordens_producao', sa.Column('situacao_op', sa.String(length=4), nullable=True))
    op.add_column('ordens_producao', sa.Column('sincronizado_em', app.tipos.DataHoraFuso(timezone=True), nullable=True))
    op.add_column('ordens_producao', sa.Column('dados_mega', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))
    # No SQLite a restrição só entra recriando a tabela (modo batch); no PostgreSQL é um ALTER TABLE comum.
    with op.batch_alter_table('ordens_producao') as tabela:
        tabela.create_check_constraint('ck_ordens_producao_origem', "origem IN ('manual', 'planilha', 'mega')")


def downgrade() -> None:
    with op.batch_alter_table('ordens_producao') as tabela:
        tabela.drop_constraint('ck_ordens_producao_origem', type_='check')
    op.drop_column('ordens_producao', 'dados_mega')
    op.drop_column('ordens_producao', 'sincronizado_em')
    op.drop_column('ordens_producao', 'situacao_op')
    op.drop_column('ordens_producao', 'origem')
