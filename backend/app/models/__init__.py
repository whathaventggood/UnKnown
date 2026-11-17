from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, UniqueConstraint, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

def uid(): return uuid4().hex

def now(): return datetime.now(timezone.utc).isoformat()

class Discipline(Base):
    __tablename__ = 'disciplines'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str]
    color: Mapped[str]
    description: Mapped[str] = mapped_column(Text, default='')
    taxonomy_version: Mapped[str] = mapped_column(default='1')

class Subfield(Base):
    __tablename__ = 'subfields'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    discipline_id: Mapped[str] = mapped_column(ForeignKey('disciplines.id'),index=True)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(Text,default='知识库人工整理的细分领域；非严格百科分类树。')
    mapping_basis: Mapped[str] = mapped_column(default='taxonomy v1 curated')
    __table_args__ = (UniqueConstraint('discipline_id','name'),)

class Topic(Base):
    __tablename__ = 'topics'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str]
    original_title: Mapped[str] = mapped_column(default='')
    summary: Mapped[str] = mapped_column(Text, default='')
    original_summary: Mapped[str] = mapped_column(Text, default='')
    language: Mapped[str] = mapped_column(default='en')
    primary_discipline_id: Mapped[str] = mapped_column(ForeignKey('disciplines.id'), index=True)
    subfield: Mapped[str] = mapped_column(default='')
    subfield_id: Mapped[str | None] = mapped_column(ForeignKey('subfields.id'),index=True)
    question: Mapped[str] = mapped_column(default='')
    value: Mapped[str] = mapped_column(default='')
    quality_score: Mapped[float] = mapped_column(default=0.65)
    quality_features: Mapped[dict] = mapped_column(JSON, default=dict)
    content_version: Mapped[str] = mapped_column(default='1')
    data_kind: Mapped[str] = mapped_column(default='seed')

class TopicDiscipline(Base):
    __tablename__ = 'topic_disciplines'
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), primary_key=True)
    discipline_id: Mapped[str] = mapped_column(ForeignKey('disciplines.id'), primary_key=True)
    mapping_basis: Mapped[str] = mapped_column(default='curated taxonomy v1')

class TopicSource(Base):
    __tablename__ = 'topic_sources'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), index=True)
    platform: Mapped[str]
    external_id: Mapped[str]
    url: Mapped[str]
    title: Mapped[str]
    language: Mapped[str] = mapped_column(default='en')
    license: Mapped[str] = mapped_column(default='unknown; see original')
    fetched_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str | None]
    version: Mapped[str | None]
    content_hash: Mapped[str] = mapped_column(default='')
    excerpt: Mapped[str] = mapped_column(Text, default='')
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint('topic_id', 'platform', 'external_id'),)

class TopicRelation(Base):
    __tablename__ = 'topic_relations'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    source_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), index=True)
    type: Mapped[str]
    label: Mapped[str]
    explanation: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str]
    direction: Mapped[str] = mapped_column(default='forward')
    property_id: Mapped[str | None]

class Profile(Base):
    __tablename__ = 'anonymous_profiles'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(unique=True)
    timezone: Mapped[str] = mapped_column(default='Asia/Shanghai')
    familiar_disciplines: Mapped[list] = mapped_column(JSON, default=list)
    depth: Mapped[str] = mapped_column(default='beginner')
    intensity: Mapped[float] = mapped_column(default=0.7)
    broad_use_history: Mapped[bool] = mapped_column(default=True)
    onboarding_complete: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[str] = mapped_column(default=now)

class TopicState(Base):
    __tablename__ = 'user_topic_states'
    profile_id: Mapped[str] = mapped_column(ForeignKey('anonymous_profiles.id', ondelete='CASCADE'), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), primary_key=True)
    familiarity: Mapped[str] = mapped_column(default='unknown')
    learning: Mapped[str] = mapped_column(default='none')
    first_explored_at: Mapped[str | None] = mapped_column(index=True)
    last_visited_at: Mapped[str | None]
    skipped_until: Mapped[str | None]

class TopicEvent(Base):
    __tablename__ = 'user_topic_events'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    profile_id: Mapped[str] = mapped_column(ForeignKey('anonymous_profiles.id', ondelete='CASCADE'), index=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), index=True)
    action: Mapped[str]
    idempotency_key: Mapped[str]
    created_at: Mapped[str] = mapped_column(default=now, index=True)
    __table_args__ = (UniqueConstraint('profile_id', 'idempotency_key'),)

class Bookmark(Base):
    __tablename__ = 'bookmarks'
    profile_id: Mapped[str] = mapped_column(ForeignKey('anonymous_profiles.id', ondelete='CASCADE'), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), primary_key=True)
    created_at: Mapped[str] = mapped_column(default=now)

class DailyRecommendation(Base):
    __tablename__ = 'daily_recommendations'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    profile_id: Mapped[str] = mapped_column(ForeignKey('anonymous_profiles.id', ondelete='CASCADE'), index=True)
    date: Mapped[str]
    mode: Mapped[str]
    batch_number: Mapped[int]
    parent_id: Mapped[str | None] = mapped_column(ForeignKey('daily_recommendations.id', ondelete='SET NULL'))
    idempotency_key: Mapped[str]
    strategy_version: Mapped[str]
    seed: Mapped[int]
    constraints_json: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    settings_snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint('profile_id', 'date', 'mode', 'batch_number'), UniqueConstraint('profile_id', 'idempotency_key'))

class RecommendationItem(Base):
    __tablename__ = 'recommendation_items'
    batch_id: Mapped[str] = mapped_column(ForeignKey('daily_recommendations.id', ondelete='CASCADE'), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id'), primary_key=True)
    position: Mapped[int]
    reason: Mapped[str] = mapped_column(Text)
    features: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float]
    bridge_path: Mapped[list] = mapped_column(JSON, default=list)

class Impression(Base):
    __tablename__ = 'exposure_events'
    batch_id: Mapped[str] = mapped_column(ForeignKey('daily_recommendations.id', ondelete='CASCADE'), primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id'), primary_key=True)
    profile_id: Mapped[str] = mapped_column(ForeignKey('anonymous_profiles.id', ondelete='CASCADE'), index=True)
    created_at: Mapped[str] = mapped_column(default=now, index=True)

class AIExplanation(Base):
    __tablename__ = 'ai_explanations'
    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), index=True)
    depth: Mapped[str]
    model: Mapped[str]
    provider_id: Mapped[str]
    evidence_version: Mapped[str]
    prompt_version: Mapped[str]
    content: Mapped[dict] = mapped_column(JSON)
    usage: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(default=now)

class AIUsage(Base):
    __tablename__ = 'ai_usage'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    profile_id: Mapped[str | None] = mapped_column(ForeignKey('anonymous_profiles.id', ondelete='SET NULL'), index=True)
    created_at: Mapped[str] = mapped_column(default=now, index=True)
    status: Mapped[str] = mapped_column(default='reserved')
    reserved_tokens: Mapped[int]
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    attempts: Mapped[int] = mapped_column(default=0)

class ChatMessage(Base):
    __tablename__ = 'chat_messages'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    profile_id: Mapped[str] = mapped_column(ForeignKey('anonymous_profiles.id', ondelete='CASCADE'), index=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey('topics.id', ondelete='CASCADE'), index=True)
    role: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(default=now)

class IngestionJob(Base):
    __tablename__ = 'ingestion_jobs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    status: Mapped[str] = mapped_column(default='pending')
    source: Mapped[str]
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    processed: Mapped[int] = mapped_column(default=0)
    failed: Mapped[int] = mapped_column(default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[str] = mapped_column(default=now)
    updated_at: Mapped[str] = mapped_column(default=now)
