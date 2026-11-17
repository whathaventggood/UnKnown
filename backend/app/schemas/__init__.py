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
class ImpressionsBody(Strict):
    batch_id: str = Field(max_length=100)
    topic_ids: list[str] = Field(max_length=20)
class FeedbackBody(Strict):
    action: Literal['known','unfamiliar','learning','understood','none','skip','unskip']
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
    familiarity: Literal['unknown','known','unfamiliar']
    learning: Literal['none','learning','understood']
    explored: bool
    skipped_until: str | None = None
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
    primary_discipline: DisciplineOut
    related_disciplines: list[DisciplineOut]
    sources: list[SourceOut]
    state: StateOut
    reading_minutes: int
    relations: list[dict] = []
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
    topic: TopicOut
    reason: str
    features: FeaturesOut
    score: float
    bridge_path: list[dict]
class DailyOut(RecommendationOut):
    items: list[RecommendationItemOut]
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
class MapNodeOut(BaseModel):
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
class ChatHistoryOut(BaseModel):
    items: list[dict]

class ErrorDetailOut(BaseModel):
    code: str
    message: str
    request_id: str
class ErrorOut(BaseModel):
    error: ErrorDetailOut
