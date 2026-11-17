import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, case
from collections import Counter,defaultdict,deque
from app.models import *
from app.services.catalog import topic_json, topics_json, source_json
from app.services.snapshots import pack_snapshot
from app.recommendation import recommend
from app.recommendation.engine import surprise
from app.services.paths import reliable


def settings_snapshot(p):
    return {k:getattr(p,k) for k in ('timezone','familiar_disciplines','depth','intensity','broad_use_history')}


def local_date(p): return datetime.now(ZoneInfo(p.timezone)).date().isoformat()


def history_snapshot(db,p):
    states=list(db.scalars(select(TopicState).where(TopicState.profile_id==p.id)))
    topics={t.id:t for t in db.execute(select(Topic.id,Topic.title,Topic.original_title,Topic.primary_discipline_id,Topic.subfield,Topic.semantic_features))}
    clock=datetime.now(timezone.utc)
    cutoff=lambda days:(clock-timedelta(days=days)).isoformat()
    explored=[s.topic_id for s in states if s.first_explored_at]
    exposure=list(db.execute(select(Impression.topic_id,func.count().label('n90'),
        func.sum(case((Impression.created_at>=cutoff(30),1),else_=0)).label('n30'),
        func.sum(case((Impression.created_at>=cutoff(14),1),else_=0)).label('n14'),
        func.sum(case((Impression.created_at>=cutoff(7),1),else_=0)).label('n7'),
        func.max(Impression.created_at).label('last')).where(Impression.profile_id==p.id,Impression.created_at>=cutoff(90)).group_by(Impression.topic_id)))
    history={'as_of':clock.isoformat(),'familiar_disciplines':p.familiar_disciplines,'intensity':p.intensity,'broad_use_history':p.broad_use_history,
        'explored_ids':explored,'explored_disciplines':sorted({topics[i].primary_discipline_id for i in explored if i in topics}),
        'explored_subfields':sorted({topics[i].subfield for i in explored if i in topics}),
        'known_ids':[s.topic_id for s in states if s.familiarity=='known'],
        'unfamiliar_ids':[s.topic_id for s in states if s.familiarity=='unfamiliar'],
        'name_only_ids':[s.topic_id for s in states if s.familiarity=='name_only'],
        'concept_only_ids':[s.topic_id for s in states if s.familiarity=='concept_only'],
        'connection_gap_ids':[s.topic_id for s in states if s.familiarity=='connections_unknown'],
        'forgotten_ids':[s.topic_id for s in states if s.familiarity=='forgotten'],
        'stale_ids':[s.topic_id for s in states if s.last_visited_at and s.last_visited_at<cutoff(90)],
        'skipped_ids':[s.topic_id for s in states if s.skipped_until and s.skipped_until>clock.isoformat()],
        'recent_ids':sorted(r.topic_id for r in exposure if r.n14),
        'exposure_counts':{r.topic_id:r.n30 for r in exposure if r.n30},'coverage_windows':{}}
    for days in (7,30,90):
        window=[s for s in states if s.first_explored_at and s.first_explored_at>=cutoff(days) and s.topic_id in topics]
        dids=Counter(topics[s.topic_id].primary_discipline_id for s in window)
        subs=Counter(topics[s.topic_id].subfield for s in window)
        history['coverage_windows'][str(days)]={'disciplines':dict(dids),'subfields':dict(subs),'first_explorations':len(window)}
    origins=set(explored+history['known_ids'])|{t.id for t in topics.values() if t.primary_discipline_id in p.familiar_disciplines}
    adjacency=defaultdict(list)
    relations=list(db.scalars(select(TopicRelation).order_by(TopicRelation.id)))
    for r in relations:
        if not reliable(r): continue
        if r.source_id not in topics or r.target_id not in topics: continue
        adjacency[r.source_id].append((r,r.target_id))
        if r.direction=='both': adjacency[r.target_id].append((r,r.source_id))
    paths={};seen=set(origins);queue=deque((tid,[]) for tid in sorted(origins))
    # Multi-source BFS: each node expanded once. Bounds are global, not per origin.
    examined=0
    while queue and examined<10000:
        start,path=queue.popleft();examined+=1
        if len(path)>=3: continue
        for r,target in adjacency[start]:
            if target in seen: continue
            hop={'from_id':start,'from_title':topics[start].title,'from_discipline_id':topics[start].primary_discipline_id,
                 'to_id':target,'to_title':topics[target].title,'type':r.type,'label':r.label,'explanation':r.explanation,
                 'source_url':r.source_url,'direction':r.direction,'relation_id':r.id,'evidence_status':getattr(r,'evidence_status','curated')}
            seen.add(target);paths[target]=path+[hop];queue.append((target,paths[target]))
    recent=[r.topic_id for r in sorted(exposure,key=lambda r:(r.last,r.topic_id),reverse=True) if r.n14 and r.topic_id in topics][:200]
    history['recent_candidates']=[{'id':i,'title':topics[i].title,'original_title':topics[i].original_title,'subfield':topics[i].subfield,'semantic_features':topics[i].semantic_features} for i in recent]
    history['bridge_paths']=paths
    history['bridge_search']={'expanded':examined,'limit':10000,'truncated':bool(queue)}
    return history


def candidate_snapshot(db):
    query=select(Topic).order_by(Topic.id).limit(10000)
    topics=list(db.scalars(query))
    sources=defaultdict(list)
    ids=select(query.subquery().c.id)
    for source in db.scalars(select(TopicSource).where(TopicSource.topic_id.in_(ids)).order_by(TopicSource.id)):
        sources[source.topic_id].append({k:getattr(source,k) for k in ('id','platform','external_id','url','license','content_hash','version')})
    return [{k:getattr(t,k) for k in ('id','title','original_title','primary_discipline_id','subfield','summary','quality_score','quality_features','content_status','semantic_features')}|{'summary':(t.content_intro.get('explanation') or t.summary) if t.content_status=='PUBLISHED' else t.summary,'sources':sources[t.id]} for t in topics]


def latest_batch(db,p,date,mode):
    return db.scalar(select(DailyRecommendation).where(DailyRecommendation.profile_id==p.id,DailyRecommendation.date==date,DailyRecommendation.mode==mode).order_by(DailyRecommendation.batch_number.desc()).limit(1))


def create_batch(db,p,mode,key=None,*,surprise_spec=None,config=None):
    # Serialize creation across local processes before reading current batch.
    raw=db.connection().connection.driver_connection
    if hasattr(raw,'in_transaction') and not raw.in_transaction:
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    today=local_date(p)
    latest=latest_batch(db,p,today,mode)
    if key:
        prior=db.scalar(select(DailyRecommendation).where(DailyRecommendation.profile_id==p.id,DailyRecommendation.idempotency_key==key))
        if prior:
            if prior.mode!=mode: raise ValueError('IDEMPOTENCY_CONFLICT')
            return prior
    elif latest: return latest
    if key:
        cutoff=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        used=db.scalar(select(func.count()).select_from(DailyRecommendation).where(DailyRecommendation.profile_id==p.id,DailyRecommendation.created_at>=cutoff))
        if used>=30: raise ValueError('REFRESH_LIMIT')
    number=latest.batch_number+1 if latest else 1
    seed=int(hashlib.sha256(f'{p.id}|{today}|{mode}|{number}'.encode()).hexdigest()[:8],16)
    candidates=candidate_snapshot(db)
    history={} if surprise_spec and surprise_spec['history_free'] else {'broad_use_history':False} if mode=='broad' and not p.broad_use_history else history_snapshot(db,p)
    result=surprise(candidates,history,seed=seed,config=config,**surprise_spec) if surprise_spec else recommend(candidates,history,mode=mode,count=5,seed=seed,config=config)
    batch=DailyRecommendation(profile_id=p.id,date=today,mode=mode,batch_number=number,parent_id=latest.id if latest else None,idempotency_key=key or f'initial:{today}:{mode}',strategy_version=result['strategy_version'],seed=seed,constraints_json=result['constraints'],snapshot=pack_snapshot(db,candidates,history,result),settings_snapshot=settings_snapshot(p))
    db.add(batch); db.flush()
    for position,item in enumerate(result['items']):
        db.add(RecommendationItem(batch_id=batch.id,topic_id=item['topic_id'],position=position,reason=item['reason'],features=item['features'],score=item['score'],bridge_path=item.get('bridge_path',[])))
    db.flush()
    return batch


def named_path(db,path,titles=None):
    result=[]
    for hop in path:
        item=dict(hop)
        for endpoint in ('from','to'):
            tid=hop[endpoint+'_id']
            if titles is not None: item[endpoint+'_title']=titles.get(tid,'主题暂不可用')
            else:
                topic=db.get(Topic,tid)
                item[endpoint+'_title']=topic.title if topic else '主题暂不可用'
        result.append(item)
    return result


def batch_json(db,b,p):
    items=list(db.scalars(select(RecommendationItem).where(RecommendationItem.batch_id==b.id).order_by(RecommendationItem.position)))
    topics=list(db.scalars(select(Topic).where(Topic.id.in_([i.topic_id for i in items]))))
    serialized={t['id']:t for t in topics_json(db,topics,p.id)}
    endpoints={hop[e+'_id'] for i in items for hop in i.bridge_path for e in ('from','to')}
    titles=dict(db.execute(select(Topic.id,Topic.title).where(Topic.id.in_(endpoints))).all()) if endpoints else {}
    evidence={i['topic_id']:i.get('feature_evidence',{}) for i in b.snapshot.get('result',{}).get('items',[])}
    rendered=[{'topic':serialized[i.topic_id],'reason':i.reason,'features':i.features,'score':i.score,'bridge_path':named_path(db,i.bridge_path,titles),'feature_evidence':evidence.get(i.topic_id,{})} for i in items if i.topic_id in serialized and serialized[i.topic_id]['content_status']=='PUBLISHED']
    constraints=dict(b.constraints_json)
    if len(rendered)<len(items):
        constraints={**constraints,'reason_codes':[*constraints.get('reason_codes',[]),'CONTENT_CHANGED_SINCE_BATCH'],'message':'部分材料在本批次生成后已不满足准入条件。原快照保留，当前展示已停止；可主动换组。','current_available':len(rendered)}
    return {'id':b.id,'date':b.date,'mode':b.mode,'batch_number':b.batch_number,'parent_id':b.parent_id,'strategy_version':b.strategy_version,'seed':b.seed,'constraints':constraints,'settings_changed':b.settings_snapshot!=settings_snapshot(p),'items':rendered}
