"""graph tables

Revision ID: 5843df747443
Revises: e2bf6858ccba
Create Date: 2026-08-18 13:49:12.255524

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5843df747443'
down_revision: str | Sequence[str] | None = 'e2bf6858ccba'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("lang", sa.String(16), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("parsed_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_files_repo_path", "files", ["repo_id", "path"], unique=True)
    op.create_table(
        "symbols",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), nullable=False),
        sa.Column("file_id", sa.Integer(),
                  sa.ForeignKey("files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("qualified_name", sa.String(512), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
    )
    op.create_index("ix_symbols_repo_qualified", "symbols", ["repo_id", "qualified_name"])
    op.create_table(
        "edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), nullable=False),
        sa.Column("src_symbol_id", sa.Integer(),
                  sa.ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dst_symbol_id", sa.Integer(),
                  sa.ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True),
        sa.Column("dst_qualified_name", sa.String(512), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
    )
    op.create_index("ix_edges_src", "edges", ["src_symbol_id"])
    op.create_index("ix_edges_dst", "edges", ["dst_symbol_id"])


def downgrade() -> None:
    op.drop_table("edges")
    op.drop_table("symbols")
    op.drop_table("files")
