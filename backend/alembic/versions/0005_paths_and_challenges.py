"""Relation evidence status, voluntary saved paths and private self-check attempts."""
from alembic import op
import sqlalchemy as sa
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('topic_relations',sa.Column('evidence_status',sa.String(),nullable=False,server_default='pending'))
    op.add_column('topic_relations',sa.Column('evidence_excerpt',sa.Text(),nullable=False,server_default=''))
    op.create_index('ix_topic_relations_evidence_status','topic_relations',['evidence_status'])
    op.execute("UPDATE topic_relations SET evidence_status='curated' WHERE source_url<>'' AND type IN ('fact','teaching') AND source_id IN (SELECT id FROM topics WHERE data_kind='seed')")
    op.create_table('saved_exploration_paths',
        sa.Column('id',sa.String(),primary_key=True),sa.Column('profile_id',sa.String(),sa.ForeignKey('anonymous_profiles.id',ondelete='CASCADE'),nullable=False),
        sa.Column('title',sa.String(),nullable=False),sa.Column('topic_ids',sa.JSON(),nullable=False),sa.Column('relation_ids',sa.JSON(),nullable=False),
        sa.Column('evidence_snapshot',sa.JSON(),nullable=False),sa.Column('position',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('idempotency_key',sa.String(),nullable=False),sa.Column('created_at',sa.String(),nullable=False),
        sa.UniqueConstraint('profile_id','idempotency_key'))
    op.create_index('ix_saved_exploration_paths_profile_id','saved_exploration_paths',['profile_id'])
    op.create_table('challenge_attempts',
        sa.Column('id',sa.String(),primary_key=True),sa.Column('profile_id',sa.String(),sa.ForeignKey('anonymous_profiles.id',ondelete='CASCADE'),nullable=False),
        sa.Column('topic_id',sa.String(),sa.ForeignKey('topics.id',ondelete='CASCADE'),nullable=False),
        sa.Column('challenge_id',sa.String(),nullable=False),sa.Column('answer',sa.Text(),nullable=False),sa.Column('feedback',sa.JSON(),nullable=False),
        sa.Column('self_assessment',sa.String(),nullable=True),sa.Column('idempotency_key',sa.String(),nullable=False),sa.Column('created_at',sa.String(),nullable=False),
        sa.UniqueConstraint('profile_id','idempotency_key'))
    op.create_index('ix_challenge_attempts_profile_id','challenge_attempts',['profile_id'])
    op.create_index('ix_challenge_attempts_topic_id','challenge_attempts',['topic_id'])


def downgrade():
    op.drop_table('challenge_attempts');op.drop_table('saved_exploration_paths')
    op.drop_index('ix_topic_relations_evidence_status',table_name='topic_relations')
    op.drop_column('topic_relations','evidence_excerpt');op.drop_column('topic_relations','evidence_status')
