from datetime import datetime,timedelta,timezone
from collections import Counter,deque
import hashlib
from sqlalchemy import select,or_
from app.models import *
from app.services.catalog import discipline_json
from app.services.paths import reliable


def stats(db,p):
    topics={t.id:t for t in db.execute(select(Topic.id,Topic.title,Topic.primary_discipline_id,Topic.subfield,Topic.subfield_id))}
    disciplines={d.id:d for d in db.scalars(select(Discipline))}
    states=list(db.scalars(select(TopicState).where(TopicState.profile_id==p.id,TopicState.first_explored_at.is_not(None)).order_by(TopicState.first_explored_at.desc())))
    first={}
    for s in reversed(states): first.setdefault(topics[s.topic_id].primary_discipline_id,s.first_explored_at)
    cutoff=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
    counts=Counter(topics[s.topic_id].primary_discipline_id for s in states if s.first_explored_at>=cutoff)
    relations={(r.source_id,r.target_id):r for r in db.scalars(select(TopicRelation).where(TopicRelation.evidence_status.in_(('curated','source_checked')))) if reliable(r)}
    paths=[]
    for a,b in zip(reversed(states[1:]),reversed(states[:-1])):
        if topics[a.topic_id].primary_discipline_id==topics[b.topic_id].primary_discipline_id: continue
        r=relations.get((a.topic_id,b.topic_id))
        if r: paths.append({'from_title':topics[a.topic_id].title,'to_title':topics[b.topic_id].title,'relation_type':r.type,'explanation':r.explanation,'source_url':r.source_url})
    last={}
    for s in states:
        did=topics[s.topic_id].primary_discipline_id
        last[did]=max(last.get(did,''),s.last_visited_at or s.first_explored_at)
    windows={}
    for days in (7,30,90):
        threshold=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        window=[s for s in states if s.first_explored_at>=threshold]
        distribution=Counter(topics[s.topic_id].primary_discipline_id for s in window)
        windows[str(days)]={'first_explorations':len(window),'main_disciplines':len(distribution),'subfields':len({topics[s.topic_id].subfield_id or topics[s.topic_id].subfield for s in window}),
            'new_disciplines':[did for did,at in first.items() if at>=threshold],
            'distribution':[{'id':did,'name':disciplines[did].name,'count':count} for did,count in sorted(distribution.items())]}
    current=list(db.scalars(select(TopicState).where(TopicState.profile_id==p.id)))
    explicit=[s for s in current if s.familiarity!='unknown'];worthwhile=[s for s in current if s.worthwhile is not None]
    attempts=list(db.scalars(select(ChallengeAttempt).where(ChallengeAttempt.profile_id==p.id)))
    saved=list(db.scalars(select(SavedPath).where(SavedPath.profile_id==p.id)))
    continued=set(db.scalars(select(TopicEvent.idempotency_key).where(TopicEvent.profile_id==p.id,TopicEvent.action=='path_continue')))
    feedback_metrics={'self_reported_unfamiliar_ratio':sum(s.familiarity=='unfamiliar' for s in explicit)/len(explicit) if explicit else None,
        'explicit_familiarity_topics':len(explicit),'self_reported_worthwhile_ratio':sum(s.worthwhile for s in worthwhile)/len(worthwhile) if worthwhile else None,'worthwhile_feedback_topics':len(worthwhile),
        'saved_path_continuation_ratio':sum(any(k.startswith('path:'+path.id+':') for k in continued) for path in saved)/len(saved) if saved else None,
        'self_reported_understood_count':sum(s.learning=='understood' for s in current),
        'challenge_attempts':len(attempts),'challenge_correctness_ratio':None,
        'challenge_self_assessment':dict(Counter(a.self_assessment for a in attempts if a.self_assessment)),
        'revisit_topics':sum(s.revisit_at is not None for s in current),
        'definitions':'比例仅使用明确反馈的主题或已保存路径；没有反馈分母时为 null。自测为参考对照，没有自动正确率或长期掌握指标。'}
    return {'explored_count':len(states),'discipline_count':len(first),'bookmark_count':len(list(db.scalars(select(Bookmark).where(Bookmark.profile_id==p.id)))),'new_disciplines':[discipline_json(disciplines[did])|{'first_explored_at':at} for did,at in sorted(first.items(),key=lambda x:x[1],reverse=True)[:6]],'distribution':[discipline_json(disciplines[did])|{'count':count} for did,count in sorted(counts.items())],'unexplored_disciplines':[discipline_json(d) for did,d in disciplines.items() if did not in first],'long_unexplored_disciplines':[discipline_json(disciplines[did])|{'last_explored_at':at} for did,at in last.items() if at<cutoff],'timeline':[{'topic_id':s.topic_id,'title':topics[s.topic_id].title,'discipline_name':disciplines[topics[s.topic_id].primary_discipline_id].name,'at':s.first_explored_at} for s in states[:100]],'paths':paths[-20:],'coverage_windows':windows,'feedback_metrics':feedback_metrics,'definitions':{'exploration':'首次成功打开详情计为探索；不代表理解。主题按稳定 ID 去重，累计范围为当前档案。','distribution':'最近 30×24 小时内首次探索的去重主题，按唯一主学科统计；分母为该窗口内首次探索总数。','discipline_count':'累计已探索主题涉及的唯一主学科数；知识库学科总数 '+str(len(disciplines))+'。','unexplored':'仅指当前知识库尚无探索记录的学科；长期未探索为超过 30 天未访问。','paths':'仅显示连续探索中具有有据定向关系的跨学科跳转；不推断未记录路径。'}}


def subfield_id(t): return t.subfield_id or 'subfield:'+hashlib.sha256(f'{t.primary_discipline_id}|{t.subfield or "一般主题"}'.encode()).hexdigest()[:16]


def graph(db,p,scope='all',discipline=None,q='',root=None,limit=80,depth=1):
    catalog=list(db.execute(select(Topic.id,Topic.title,Topic.summary,Topic.primary_discipline_id,Topic.subfield,Topic.subfield_id,Topic.content_status).order_by(Topic.id).limit(10001)))
    catalog_truncated=len(catalog)>10000
    all_topics=catalog[:10000];by_id={t.id:t for t in all_topics}
    disciplines={d.id:d for d in db.scalars(select(Discipline))}
    states={s.topic_id:s for s in db.scalars(select(TopicState).where(TopicState.profile_id==p.id))}
    bookmarks=set(db.scalars(select(Bookmark.topic_id).where(Bookmark.profile_id==p.id)))
    counts=Counter(by_id[tid].primary_discipline_id for tid,s in states.items() if tid in by_id and s.first_explored_at)
    allowed=[t for t in all_topics if (not discipline or t.primary_discipline_id==discipline) and (not q or q.casefold() in (t.title+' '+t.summary).casefold()) and (scope!='explored' or t.id in states and states[t.id].first_explored_at)]
    search_truncated=False
    if root:
        tid=root.removeprefix('topic:')
        if root.startswith('discipline:'): allowed=[t for t in allowed if t.primary_discipline_id==root[11:]]
        elif root.startswith('subfield:'): allowed=[t for t in allowed if subfield_id(t)==root]
        else:
            ids={tid};frontier={tid}
            for _ in range(depth):
                rows=list(db.scalars(select(TopicRelation).where(TopicRelation.evidence_status.in_(('curated','source_checked')),or_(TopicRelation.source_id.in_(frontier),TopicRelation.target_id.in_(frontier))).order_by(TopicRelation.id).limit(1001)))
                if len(rows)>1000: search_truncated=True
                new={endpoint for r in rows[:1000] if reliable(r) for endpoint in (r.source_id,r.target_id)}-ids
                ids|=new;frontier=new
                if not frontier: break
            allowed=[t for t in allowed if t.id in ids]
    buckets={did:deque(t for t in allowed if t.primary_discipline_id==did) for did in disciplines}
    ordered=[]
    while any(buckets.values()):
        for bucket in buckets.values():
            if bucket: ordered.append(bucket.popleft())
    if root and not root.startswith(('discipline:','subfield:')):
        ordered.sort(key=lambda t:t.id!=root.removeprefix('topic:'))
    budget=set();selected=[]
    for t in ordered:
        if len(budget)>=limit: break
        needed={'discipline:'+t.primary_discipline_id,subfield_id(t),'topic:'+t.id}
        if len(budget|needed)>limit: continue
        budget|=needed;selected.append(t)
    sids={subfield_id(t) for t in selected}
    subfields={s.id:s.description for s in db.scalars(select(Subfield).where(Subfield.id.in_(sids)))} if sids else {}
    nodes={};edges=[]
    for t in selected:
        did='discipline:'+t.primary_discipline_id;sid=subfield_id(t);tid='topic:'+t.id;d=disciplines[t.primary_discipline_id]
        common={'discipline_id':d.id,'color':d.color,'topic_id':None,'explored':False,'bookmarked':False,'learning':'none','count':0}
        nodes.setdefault(did,dict(common,id=did,name=d.name,type='discipline',description=d.description,count=counts[d.id]))
        if sid not in nodes:
            nodes[sid]=dict(common,id=sid,name=t.subfield or '一般主题',type='subfield',description=subfields.get(sid,'人工整理的细分分类，不表示严格百科树。'))
            edges.append({'id':did+'|'+sid,'source':did,'target':sid,'type':'taxonomy','label':'细分领域','explanation':'UnKnown 学科体系 v1 人工映射。','source_url':''})
        st=states.get(t.id)
        nodes[tid]=dict(common,id=tid,name=t.title,type='topic',topic_id=t.id,description=t.summary,explored=bool(st and st.first_explored_at),bookmarked=t.id in bookmarks,learning=st.learning if st else 'none',familiarity=st.familiarity if st else 'unknown',content_status=t.content_status)
        edges.append({'id':sid+'|'+tid,'source':sid,'target':tid,'type':'taxonomy','label':'学科归属','explanation':'唯一统计主学科与人工分类映射。','source_url':''})
    selected_ids=[t.id for t in selected]
    relations=list(db.scalars(select(TopicRelation).where(TopicRelation.evidence_status.in_(('curated','source_checked')),TopicRelation.source_id.in_(selected_ids),TopicRelation.target_id.in_(selected_ids)).order_by(TopicRelation.id).limit(301))) if selected_ids else []
    for r in relations:
        if reliable(r): edges.append({'id':r.id,'source':'topic:'+r.source_id,'target':'topic:'+r.target_id,'type':r.type,'label':r.label,'explanation':r.explanation,'source_url':r.source_url,'direction':r.direction})
    return {'nodes':list(nodes.values()),'edges':edges[:300],'truncated':catalog_truncated or search_truncated or len(selected)<len(allowed) or len(edges)>300,'limits':{'nodes':limit,'edges':300,'depth':depth},'legend':'颜色表示主学科；菱形为自述已理解。探索、理解自述与收藏独立；当前知识库包含尚未发布的资料。'}
