"""add profit tracking fields

Revision ID: 8b3b7f2d2c11
Revises: 6244c0e5a2f7
Create Date: 2026-04-23

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8b3b7f2d2c11"
down_revision: Union[str, Sequence[str], None] = "b5d8a6193b2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("cost_price_per_kg", sa.Numeric(precision=10, scale=2), nullable=True),
    )

    op.add_column(
        "order_items",
        sa.Column("cost_price_per_kg", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("profit", sa.Numeric(precision=12, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_items", "profit")
    op.drop_column("order_items", "cost_price_per_kg")
    op.drop_column("products", "cost_price_per_kg")
