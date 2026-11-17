from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Mode = Literal['unknown','bridge','broad']
Depth = Literal['beginner','intermediate','deep']

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class ProfilePatch(Strict):
    timezone: str | None = Field(None,min_length=1,max_length=80)
    familiar_disciplines: list[str] | None = Field(None,max_length=20)
    depth: Depth | None = None
    intensity: float | None = Field(None,ge=0,le=1)
    broad_use_history: bool | None = None
    onboarding_complete: bool | None = None
    @field_validator('timezone')
    @classmethod
    def tz(cls,v):
        if v is not None:
            try: ZoneInfo(v)
            except (ZoneInfoNotFoundError,ValueError): raise ValueError('Unknown IANA timezone')
        return v

class RefreshBody(Strict):
    mode: Mode = 'unknown'
    idempotency_key: str = Field(min_length=8,max_length=100)
class SurpriseBody(Strict):
    strength: Literal['gentle','cross','far'] = 'cross'
    history_free: bool = False
    idempotency_key: str = Field(min_length=8,max_length=100)
class SavePathBody(Strict):
    topic_ids: list[str] = Field(min_length=2,max_length=5)
    relation_ids: list[str] = Field(min_length=1,max_length=4)
    idempotency_key: str = Field(min_length=8,max_length=100)
class PathPositionBody(Strict):
    position: int = Field(ge=0,le=4)
class ChallengeBody(Strict):
    challenge_id: str = Field(min_length=10,max_length=100)
    answer: str = Field(min_length=1,max_length=2000)
    idempotency_key: str = Field(min_length=8,max_length=100)
    self_assessment: Literal['not_yet','partial','got_it'] | None = None
    @field_validator('answer')
    @classmethod
    def not_blank(cls,value):
        if not value.strip(): raise ValueError('Answer must not be blank')
        return value.strip()
class AssessmentBody(Strict):
    self_assessment: Literal['not_yet','partial','got_it']
class ImpressionsBody(Strict):
    batch_id: str = Field(max_length=100)
    topic_ids: list[str] = Field(max_length=20)
class FeedbackBody(Strict):
    action: Literal['known','unfamiliar','name_only','concept_only','connections_unknown','forgotten','learning','understood','none','skip','unskip','revisit','cancel_revisit','worthwhile','not_worthwhile']
    idempotency_key: str = Field(min_length=8,max_length=100)
class BookmarkBody(Strict):
    topic_id: str = Field(min_length=1,max_length=150)
class ResetBody(Strict):
    confirm: Literal[True]
class ExplainBody(Strict):
    topic_id: str = Field(min_length=1,max_length=150)
    depth: Depth = 'beginner'
    language: Literal['zh'] = 'zh'
class ChatBody(ExplainBody):
    message: str = Field(min_length=1,max_length=2000)
    @field_validator('message')
    @classmethod
    def nonblank(cls,v):
        if not v.strip(): raise ValueError('Message must not be blank')
        return v.strip()

# Response schemas document stable frontend-facing fields and validate outgoing data.
class DisciplineOut(BaseModel):
    id: str
    name: str
    color: str
    description: str = ''
class SourceOut(BaseModel):
    id: str
    platform: str
    external_id: str
    url: str
    title: str
    language: str
    license: str
    fetched_at: str
    updated_at: str | None = None
    version: str | None = None
    content_hash: str
    excerpt: str
class StateOut(BaseModel):
    bookmarked: bool
    familiarity: Literal['unknown','known','unfamiliar','name_only','concept_only','connections_unknown','forgotten']
    learning: Literal['none','learning','understood']
    explored: bool
    skipped_until: str | None = None
    revisit_at: str | None = None
    worthwhile: bool | None = None
class TopicOut(BaseModel):
    id: str
    title: str
    original_title: str
    summary: str
    original_summary: str
    language: str
    subfield: str
    question: str
    value: str
    quality_score: float
    quality_features: dict = {}
    data_kind: str
    content_status: str = 'RAW'
    content_intro: dict = {}
    content_checks: dict = {}
    processed_at: str | None = None
    primary_discipline: DisciplineOut
    related_disciplines: list[DisciplineOut]
    sources: list[SourceOut]
    state: StateOut
    reading_minutes: int
    relations: list[dict] = []
    relations_truncated: bool = False
class ProfileOut(BaseModel):
    id: str
    timezone: str
    familiar_disciplines: list[str]
    depth: Depth
    intensity: float
    broad_use_history: bool
    onboarding_complete: bool
    ai: dict
class CollectionOut(BaseModel):
    items: list[TopicOut]
    total: int
class RecommendationOut(BaseModel):
    id: str
    date: str
    mode: Mode
    batch_number: int
    parent_id: str | None
    items: list[dict]
    constraints: dict
    strategy_version: str
    seed: int
    settings_changed: bool

class RelationOut(BaseModel):
    id: str
    type: str
    label: str
    explanation: str
    source_url: str
    direction: str = 'forward'
    source_id: str | None = None
    target_id: str | None = None
    property_id: str | None = None
    source_title: str
    target_title: str
    evidence_status: str = 'pending'
    evidence_excerpt: str = ''
class RelatedItemOut(BaseModel):
    topic: TopicOut
    relation: RelationOut
class RelatedOut(BaseModel):
    items: list[RelatedItemOut]
class FeaturesOut(BaseModel):
    novelty: float = Field(ge=0,le=1)
    quality: float = Field(ge=0,le=1)
    diversity: float = Field(ge=0,le=1)
    learnability: float = Field(ge=0,le=1)
class RecommendationItemOut(BaseModel):
    feature_evidence: dict = {}
    topic: TopicOut
    reason: str
    features: FeaturesOut
    score: float
    bridge_path: list[dict]
class DailyOut(RecommendationOut):
    items: list[RecommendationItemOut]
class SurpriseOut(BaseModel):
    id: str
    strength: str
    history_free: bool
    item: RecommendationItemOut | None
    constraints: dict
class StateResponse(BaseModel):
    state: StateOut
class DisciplinesOut(BaseModel):
    items: list[DisciplineOut]
class HealthOut(BaseModel):
    status: str
    version: str
    topics: int
    ai_configured: bool
class ImpressionOut(BaseModel):
    recorded: int
class ResetOut(BaseModel):
    cleared: bool
    message: str
class StatsOut(BaseModel):
    explored_count: int
    discipline_count: int
    bookmark_count: int
    new_disciplines: list[dict]
    distribution: list[dict]
    unexplored_disciplines: list[DisciplineOut]
    long_unexplored_disciplines: list[dict] = []
    timeline: list[dict]
    paths: list[dict]
    definitions: dict[str,str]
    coverage_windows: dict = {}
    feedback_metrics: dict = {}
class MapNodeOut(BaseModel):
    content_status: str | None = None
    id: str
    name: str
    type: Literal['discipline','subfield','topic']
    discipline_id: str
    color: str
    description: str
    topic_id: str | None
    explored: bool
    bookmarked: bool
    learning: str
    familiarity: str = 'unknown'
    count: int
class MapEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    type: str
    label: str
    explanation: str
    source_url: str
    direction: str = 'forward'
class MapOut(BaseModel):
    nodes: list[MapNodeOut]
    edges: list[MapEdgeOut]
    truncated: bool
    limits: dict[str,int]
    legend: str
class AIUsageOut(BaseModel):
    input_tokens: int
    output_tokens: int
class AIExplainOut(BaseModel):
    status: Literal['ready','unavailable']
    message: str
    cached: bool
    content: dict | None
    sources: list[SourceOut]
    usage: AIUsageOut | None
class AIChatOut(BaseModel):
    status: Literal['ready','unavailable']
    message: str
    answer: str | None
    source_ids: list[str]
    sources: list[SourceOut]
    usage: AIUsageOut | None
    evidence_refs: list[dict] = []
class ChatHistoryOut(BaseModel):
    items: list[dict]

class ErrorDetailOut(BaseModel):
    code: str
    message: str
    request_id: str
class ErrorOut(BaseModel):
    error: ErrorDetailOut

class PathsOut(BaseModel):
    items: list[dict]
    limited: bool
    message: str
    search: dict = {}
class SavedPathOut(BaseModel):
    id: str
    title: str
    topic_ids: list[str]
    relation_ids: list[str]
    hops: list[dict]
    position: int
    available: bool
    evidence_changed: bool
    created_at: str
class SavedPathsOut(BaseModel):
    items: list[SavedPathOut]
    total: int
class DeletedOut(BaseModel):
    deleted: bool
class ChallengeOut(BaseModel):
    status: str
    message: str
    challenge: dict | None
class AttemptOut(BaseModel):
    id: str
    topic_id: str
    challenge_id: str
    answer: str
    feedback: dict
    self_assessment: str | None
    created_at: str
class AttemptsOut(BaseModel):
    items: list[AttemptOut]
