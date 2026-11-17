"""Persistent content processing and conservative publication gate.

Existing learning/history tables are untouched. Previously imported topics start
unpublished until checked; startup rechecks curated seeds without remote calls.
"""
from alembic import op
import sqlalchemy as sa

revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None


def upgrade():
    op.add_column('topics',sa.Column('content_status',sa.String(),nullable=False,server_default='RAW'))
    op.add_column('topics',sa.Column('content_fingerprint',sa.String(),nullable=False,server_default=''))
    op.add_column('topics',sa.Column('content_intro',sa.JSON(),nullable=False,server_default='{}'))
    op.add_column('topics',sa.Column('content_checks',sa.JSON(),nullable=False,server_default='{}'))
    op.add_column('topics',sa.Column('processing_error',sa.Text(),nullable=True))
    op.add_column('topics',sa.Column('processed_at',sa.String(),nullable=True))
    op.add_column('topics',sa.Column('processing_attempts',sa.Integer(),nullable=False,server_default='0'))
    op.create_index('ix_topics_content_status','topics',['content_status'])
    op.execute("UPDATE topics SET content_status='EXTRACTED' WHERE EXISTS (SELECT 1 FROM topic_sources s WHERE s.topic_id=topics.id AND length(trim(s.excerpt))>=8)")


def downgrade():
    op.drop_index('ix_topics_content_status',table_name='topics')
    for column in ('processing_attempts','processed_at','processing_error','content_checks','content_intro','content_fingerprint','content_status'):
        op.drop_column('topics',column)
