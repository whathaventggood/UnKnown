"""Immutable shared compressed catalogs and saved chat evidence locations.

Legacy full JSON recommendation rows stay unchanged and remain replayable.
"""
from alembic import op
import sqlalchemy as sa
revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('recommendation_catalog_snapshots',
        sa.Column('id',sa.String(),primary_key=True),sa.Column('codec',sa.String(),nullable=False),
        sa.Column('payload',sa.LargeBinary(),nullable=False),sa.Column('topic_count',sa.Integer(),nullable=False),
        sa.Column('raw_bytes',sa.Integer(),nullable=False),sa.Column('created_at',sa.String(),nullable=False))
    op.add_column('chat_messages',sa.Column('evidence_refs',sa.JSON(),nullable=False,server_default='[]'))
    # Composite indexes follow actual profile/window and profile/list predicates.
    op.create_index('ix_exposure_profile_time','exposure_events',['profile_id','created_at'])
    op.create_index('ix_states_profile_learning','user_topic_states',['profile_id','learning'])
    op.create_index('ix_challenge_profile_topic_time','challenge_attempts',['profile_id','topic_id','created_at'])


def downgrade():
    op.drop_index('ix_challenge_profile_topic_time',table_name='challenge_attempts')
    op.drop_index('ix_states_profile_learning',table_name='user_topic_states')
    op.drop_index('ix_exposure_profile_time',table_name='exposure_events')
    op.drop_column('chat_messages','evidence_refs');op.drop_table('recommendation_catalog_snapshots')
