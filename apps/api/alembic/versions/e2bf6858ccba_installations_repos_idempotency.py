"""installations repos idempotency

Revision ID: e2bf6858ccba
Revises: 9de7d06df0d9
Create Date: 2026-08-18 13:44:31.177457

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2bf6858ccba"
down_revision: str | Sequence[str] | None = "9de7d06df0d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "installations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("account_login", sa.String(256), nullable=False),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "repos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column(
            "installation_id",
            sa.BigInteger(),
            sa.ForeignKey("installations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(256), nullable=False),
        sa.Column("default_branch", sa.String(256), nullable=False),
        sa.Column("indexed_commit", sa.String(64), nullable=True),
        sa.Column("index_status", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.create_foreign_key(
            "fk_reviews_repo_id_repos",
            "repos",
            ["repo_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "uq_reviews_repo_pr_sha",
        "reviews",
        ["repo_id", "pr_number", "head_sha"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_reviews_repo_pr_sha", table_name="reviews")
    with op.batch_alter_table("reviews") as batch_op:
        batch_op.drop_constraint("fk_reviews_repo_id_repos", type_="foreignkey")
    op.drop_table("repos")
    op.drop_table("installations")
