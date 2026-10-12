"""Add optional user feedback to assistant messages."""
from alembic import op
import sqlalchemy as sa

revision = "a91c64ef203b"
down_revision = "d8e4a61f209b"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("feedback", sa.SmallInteger(), nullable=True))
    op.create_check_constraint("ck_messages_feedback", "messages", "feedback IN (-1, 1)")


def downgrade():
    op.drop_constraint("ck_messages_feedback", "messages", type_="check")
    op.drop_column("messages", "feedback")
