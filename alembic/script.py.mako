"""${message}"""

from alembic import op
import sqlalchemy as sa

${upgrades if upgrades else "def upgrade():\n    pass"}

${downgrades if downgrades else "def downgrade():\n    pass"}

