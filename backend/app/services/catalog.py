import hashlib
import json
import math
from sqlalchemy import select, delete
from app.models import Discipline, Subfield, Topic, TopicDiscipline, TopicSource, TopicRelation, TopicState, Bookmark


def upsert_seed(db, payload, data_kind='seed'):
    """Idempotent transaction-owned import. Stable source IDs, never merge by title alone."""
    for d in payload.get('disciplines', []):
        obj = db.get(Discipline, d['id'])
        fields = {k: d[k] for k in ('id','name','color','description') if k in d}
        if obj:
            for k,v in fields.items(): setattr(obj,k,v)
        else: db.add(Discipline(**fields))
    db.flush()
    added = 0
    for t in payload.get('topics', []):
        if not t.get('sources') or not all(s.get('url','').startswith(('https://','http://')) for s in t['sources']):
            raise ValueError('Every imported topic must have traceable sources')
        obj = db.get(Topic, t['id'])
        fields = {k:t[k] for k in ('id','title','original_title','summary','original_summary','language','primary_discipline_id','subfield','question','value','quality_score','quality_features') if k in t}
        fields['content_version'] = hashlib.sha256(json.dumps(t,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        fields['data_kind'] = data_kind
        if any(s.get('platform')=='openalex' and str(s.get('external_id','')).startswith('T') for s in t['sources']):
            fields['quality_features']={**t.get('quality_features',{}),'upstream_ai':True,'summary_label':'OpenAlex 原始研究簇描述（上游 AI 生成，未专家核验）'}
        subfield_name=t.get('subfield','') or '一般主题'
        sid='subfield:'+hashlib.sha256(f"{t['primary_discipline_id']}|{subfield_name}".encode()).hexdigest()[:16]
        if not db.get(Subfield,sid):
            db.add(Subfield(id=sid,discipline_id=t['primary_discipline_id'],name=subfield_name));db.flush()
        fields['subfield_id']=sid
        if obj:
            if obj.data_kind=='seed' and data_kind=='online':
                # A source refresh must not erase the curated Chinese entry point.
                # Source versions still invalidate evidence caches independently.
                fields={k:v for k,v in fields.items() if k=='content_version'}
            for k,v in fields.items(): setattr(obj,k,v)
        else:
            db.add(Topic(**fields)); added += 1
        db.flush()
        for did in set(t.get('related_discipline_ids', []) + [t['primary_discipline_id']]):
            if db.get(Discipline,did) and not db.get(TopicDiscipline,(t['id'],did)):
                db.add(TopicDiscipline(topic_id=t['id'],discipline_id=did,mapping_basis=t.get('mapping_basis','人工整理分类 v1；非百科分类树')))
        for s in t['sources']:
            existing = db.scalar(select(TopicSource).where(TopicSource.topic_id==t['id'],TopicSource.platform==s['platform'],TopicSource.external_id==str(s['external_id'])))
            fields = {k:s[k] for k in ('platform','external_id','url','title','language','license','fetched_at','updated_at','version','content_hash','excerpt') if k in s}
            fields['external_id'] = str(fields['external_id'])
            fields['metadata_json'] = s.get('metadata_json',{})
            if existing:
                for k,v in fields.items(): setattr(existing,k,v)
            else:
                # Source external IDs alone are not globally unique across platforms/topics.
                source_id = s.get('id') or hashlib.sha256(f"{t['id']}|{s['platform']}|{s['external_id']}".encode()).hexdigest()[:32]
                db.add(TopicSource(id=source_id,topic_id=t['id'],**fields))
    db.flush()
    # Explicit imports perform only local, idempotent content checks. No LLM/network.
    from app.services.content import process_topic
    for t in payload.get('topics', []):
        process_topic(db,db.get(Topic,t['id']))
    db.flush()
    for r in payload.get('relations', []):
        if not db.get(Topic,r['source_id']) or not db.get(Topic,r['target_id']): continue
        fields={k:r[k] for k in ('id','source_id','target_id','type','label','explanation','source_url','direction','property_id','evidence_excerpt') if k in r}
        fields['evidence_status']='curated' if data_kind=='seed' and r['type'] in ('fact','teaching') else 'pending'
        if not fields.get('source_url'): continue
        rid=fields.get('id') or hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()[:32]
        obj=db.get(TopicRelation,rid)
        if obj:
            for k,v in fields.items(): setattr(obj,k,v)
        else: db.add(TopicRelation(**{**fields,'id':rid}))
    db.flush()
    return {'added':added,'processed':len(payload.get('topics',[]))}


def source_json(s):
    return {k:getattr(s,k) for k in ('id','platform','external_id','url','title','language','license','fetched_at','updated_at','version','content_hash','excerpt')}


def state_json(db, profile_id, topic_id):
    st=db.get(TopicState,(profile_id,topic_id))
    return {'bookmarked':db.get(Bookmark,(profile_id,topic_id)) is not None,'familiarity':st.familiarity if st else 'unknown','learning':st.learning if st else 'none','explored':bool(st and st.first_explored_at),'skipped_until':st.skipped_until if st else None,'revisit_at':st.revisit_at if st else None,'worthwhile':st.worthwhile if st else None}


def topic_json(db,t,profile_id):
    d=db.get(Discipline,t.primary_discipline_id)
    fields={k:getattr(t,k) for k in ('id','title','original_title','summary','original_summary','language','subfield','question','value','quality_score','quality_features','data_kind','content_status','content_intro','content_checks','processed_at')}
    fields.update(primary_discipline=discipline_json(d),related_disciplines=[discipline_json(db.get(Discipline,x.discipline_id)) for x in db.scalars(select(TopicDiscipline).where(TopicDiscipline.topic_id==t.id,TopicDiscipline.discipline_id!=t.primary_discipline_id))],sources=[source_json(s) for s in db.scalars(select(TopicSource).where(TopicSource.topic_id==t.id))],state=state_json(db,profile_id,t.id),reading_minutes=max(1,math.ceil(len(t.summary)/350)))
    return fields


def discipline_json(d):
    return {'id':d.id,'name':d.name,'color':d.color,'description':d.description}
