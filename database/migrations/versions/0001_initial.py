"""Initial encrypted applicant schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "profiles", sa.Column("id", sa.Integer, primary_key=True), sa.Column("data", sa.Text, nullable=False)
    )
    for name in ("education", "employment", "projects", "skills", "preferences"):
        op.create_table(
            name,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("profile_id", sa.Integer, sa.ForeignKey("profiles.id"), nullable=False),
            sa.Column("data", sa.Text, nullable=False),
        )
    op.create_table(
        "documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("data", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "saved_answers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("profiles.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), unique=True, nullable=False),
        sa.Column("data", sa.Text, nullable=False),
    )
    op.create_table(
        "applications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_key", sa.String(64), unique=True, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("data", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name in ("application_answers", "execution_logs"):
        columns = [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("application_id", sa.String(36), sa.ForeignKey("applications.id"), nullable=False),
            sa.Column("data", sa.Text, nullable=False),
        ]
        if name == "execution_logs":
            columns.append(sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
        op.create_table(name, *columns)


def downgrade():
    for name in (
        "execution_logs",
        "application_answers",
        "applications",
        "saved_answers",
        "documents",
        "preferences",
        "skills",
        "projects",
        "employment",
        "education",
        "profiles",
    ):
        op.drop_table(name)
