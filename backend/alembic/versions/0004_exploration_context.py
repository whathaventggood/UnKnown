"""Optional semantic cache, explicit familiarity gaps and voluntary revisits."""
from alembic import op
import sqlalchemy as sa
revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('topics',sa.Column('semantic_features',sa.JSON(),nullable=False,server_default='{}'))
    op.add_column('user_topic_states',sa.Column('revisit_at',sa.String(),nullable=True))
    op.add_column('user_topic_states',sa.Column('worthwhile',sa.Boolean(),nullable=True))
    op.create_index('ix_user_topic_states_revisit_at','user_topic_states',['profile_id','revisit_at'])


def downgrade():
    op.drop_index('ix_user_topic_states_revisit_at',table_name='user_topic_states')
    op.drop_column('user_topic_states','worthwhile')
    op.drop_column('user_topic_states','revisit_at')
    op.drop_column('topics','semantic_features')
