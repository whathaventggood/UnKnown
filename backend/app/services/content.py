"""Bounded source -> editorial entry -> structural checks -> publication.

PUBLISHED means passes local admission rules, never expert review or verified
entailment. Research-cluster metadata alone remains unpublished even with an
excellent translation. Source refreshes invalidate the fingerprint and recheck.
"""
import hashlib
import json
import re
from urllib.parse import urlsplit

from sqlalchemy import select
from app.models import TopicSource, now

PIPELINE_VERSION='content-1.0'
STATES=('RAW','EXTRACTED','ENRICHED','REVIEWED','PUBLISHED')
GENERIC=('改变你理解世界的方式','探索这个领域的无限可能','开启知识的大门')
REASONS={
    'NO_SOURCE_EXCERPT':'缺少可定位的原始来源片段。',
    'NO_LICENSE':'来源许可信息不足。',
    'NO_TRACEABLE_SOURCE':'缺少可追溯的 HTTP(S) 来源。',
    'METADATA_ONLY':'仅有研究簇元数据；需要独立入门资料，翻译不能替代证据。',
    'NO_CHINESE_INTRO':'缺少具体的中文入门简介。',
    'NO_CORE_QUESTION':'缺少核心问题。',
    'NO_VALUE':'缺少具体知识价值。',
    'GENERIC_COPY':'简介或价值包含空泛宣传语。',
    'QUALITY_FLAG':'条目被标记重复或异常。',
    'INVALID_INTRO_EVIDENCE':'加工内容引用未能定位到该来源的原文。',
}


def url_ok(value):
    try:
        p=urlsplit(value or '')
        return p.scheme in ('http','https') and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


def chinese(text,minimum=6):
    text=str(text or '')
    han=len(re.findall(r'[\u3400-\u9fff]',text))
    return han>=minimum and han/max(1,sum(c.isalpha() for c in text))>=0.35


def source_fingerprint(topic,sources):
    # Fetched timestamps are not content changes. Include actual excerpts as well
    # as upstream hashes, since an upstream hash may be absent or inaccurate.
    data={'pipeline':PIPELINE_VERSION,'editorial':[topic.title,topic.summary,topic.question,topic.value,topic.primary_discipline_id,topic.quality_features],
          'sources':[{k:getattr(s,k) for k in ('id','platform','external_id','excerpt','content_hash','version','url','license')} for s in sorted(sources,key=lambda s:s.id)]}
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def curated_intro(topic):
    return {'one_sentence':re.split(r'(?<=[。！？])',topic.summary)[0],
            'explanation':topic.summary,'entry_example':'','core_question':topic.question,
            'value':topic.value,'origin':'existing_editorial','evidence_status':'not_entailment_verified',
            'evidence_refs':[]}


def check_content(topic,sources,intro):
    issues=[]
    usable=[s for s in sources if url_ok(s.url)]
    if not usable: issues.append('NO_TRACEABLE_SOURCE')
    excerpts=[s for s in usable if len(s.excerpt.strip())>=8]
    if not excerpts: issues.append('NO_SOURCE_EXCERPT')
    if not any(s.license.strip() and not s.license.lower().startswith(('unknown','see original')) for s in excerpts): issues.append('NO_LICENSE')
    # OpenAlex topics are upstream machine-generated descriptions of clusters.
    instructional=[s for s in excerpts if not (s.platform=='openalex' and s.external_id.startswith('T'))]
    if excerpts and not instructional: issues.append('METADATA_ONLY')
    if not chinese(intro.get('one_sentence')) or not chinese(intro.get('explanation')): issues.append('NO_CHINESE_INTRO')
    if not chinese(intro.get('core_question'),2): issues.append('NO_CORE_QUESTION')
    if not chinese(intro.get('value'),2): issues.append('NO_VALUE')
    if any(text in json.dumps(intro,ensure_ascii=False) for text in GENERIC): issues.append('GENERIC_COPY')
    if any((topic.quality_features or {}).get(k) for k in ('duplicate','anomalous')): issues.append('QUALITY_FLAG')
    if intro.get('origin')=='ai_assisted':
        indexed={s.id:s.excerpt for s in excerpts}
        refs=intro.get('evidence_refs') or []
        if not refs or any(r.get('source_id') not in indexed or len(r.get('quote','').strip())<8 or r['quote'] not in indexed[r['source_id']] for r in refs): issues.append('INVALID_INTRO_EVIDENCE')
    return {'version':PIPELINE_VERSION,'issues':issues,'reasons':[REASONS[i] for i in issues],
            'check_kind':'structural_and_quote_location','expert_reviewed':False,'facts_verified':False,
            'source_count':len(usable),'excerpt_count':len(excerpts),
            'evidence_scope':'metadata_only' if excerpts and not instructional else 'source_excerpts' if instructional else 'insufficient'}


def process_topic(db,topic,*,publish=True,force=False,intro=None):
    from app.recommendation.semantic import describe
    topic.semantic_features=describe(topic.title,topic.original_title)
    sources=list(db.scalars(select(TopicSource).where(TopicSource.topic_id==topic.id).order_by(TopicSource.id)))
    fingerprint=source_fingerprint(topic,sources)
    if not force and intro is None and topic.content_fingerprint==fingerprint and not topic.processing_error:
        if publish and topic.content_status=='REVIEWED' and not topic.content_checks.get('issues'):
            topic.content_status='PUBLISHED'
            return {'topic_id':topic.id,'status':'PUBLISHED','skipped':False,'issues':[]}
        return {'topic_id':topic.id,'status':topic.content_status,'skipped':True,'issues':topic.content_checks.get('issues',[])}
    topic.processing_attempts=(topic.processing_attempts or 0)+1
    # Never silently reuse generated material following a source change.
    material=intro or (topic.content_intro if topic.content_fingerprint==fingerprint and topic.content_intro else curated_intro(topic))
    report=check_content(topic,sources,material)
    state='EXTRACTED' if report['excerpt_count'] else 'RAW'
    if report['excerpt_count'] and chinese(material.get('one_sentence')) and chinese(material.get('core_question'),2) and chinese(material.get('value'),2): state='ENRICHED'
    if not report['issues']: state='PUBLISHED' if publish else 'REVIEWED'
    topic.content_intro=material
    topic.content_status=state
    topic.content_fingerprint=fingerprint
    topic.content_checks=report
    topic.processing_error=None
    topic.processed_at=now()
    return {'topic_id':topic.id,'status':state,'skipped':False,'issues':report['issues']}
