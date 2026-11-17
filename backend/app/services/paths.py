"""Indexed, bounded BFS over published topics and admitted directed relations."""
from collections import defaultdict,deque
import hashlib
import json
from sqlalchemy import select,or_,and_
from app.models import Topic,TopicRelation
from app.services.content import url_ok

ADMITTED=('curated','source_checked')


def reliable(r):
    return r.evidence_status in ADMITTED and r.type in ('fact','teaching') and r.direction in ('forward','both') and bool(r.explanation.strip()) and url_ok(r.source_url)


def hop_json(r,start,target,topics):
    a,b=topics[start],topics[target]
    hop={'relation_id':r.id,'from_id':start,'from_title':a.title,'from_discipline_id':a.primary_discipline_id,
         'to_id':target,'to_title':b.title,'to_discipline_id':b.primary_discipline_id,'cross_discipline':a.primary_discipline_id!=b.primary_discipline_id,
         'type':r.type,'label':r.label,'explanation':r.explanation,'source_url':r.source_url,'direction':r.direction,
         'evidence_status':r.evidence_status,'evidence_excerpt':r.evidence_excerpt,
         'evidence_note':'编辑教学联系；不代表两个概念具有相同机制。' if r.type=='teaching' else '有来源链接的编辑关系；未自动验证事实蕴含。'}
    hop['fingerprint']=hashlib.sha256(json.dumps(hop,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return hop


def paths_from(db,root,*,max_hops=4,limit=3,node_limit=1000,edge_limit=4000):
    max_hops=min(4,max(1,max_hops));limit=min(6,max(1,limit))
    frontier={root};seen_nodes={root};rows={};truncated=False
    for _ in range(max_hops):
        if not frontier: break
        query=select(TopicRelation).where(TopicRelation.evidence_status.in_(ADMITTED),or_(TopicRelation.source_id.in_(frontier),and_(TopicRelation.direction=='both',TopicRelation.target_id.in_(frontier)))).order_by(TopicRelation.id).limit(edge_limit-len(rows)+1)
        found=list(db.scalars(query));new=set()
        for r in found:
            if r.id in rows or not reliable(r): continue
            if len(rows)>=edge_limit: truncated=True;break
            rows[r.id]=r
            for tid in (r.source_id,r.target_id):
                if tid not in seen_nodes:
                    if len(seen_nodes)>=node_limit: truncated=True;continue
                    new.add(tid);seen_nodes.add(tid)
        frontier=new
        if truncated: break
    topics={t.id:t for t in db.scalars(select(Topic).where(Topic.id.in_(seen_nodes),Topic.content_status=='PUBLISHED'))}
    if root not in topics: return {'items':[],'limited':truncated,'message':'此主题尚未满足内容准入，暂不构建正式探索路径。'}
    adjacency=defaultdict(list)
    for r in rows.values():
        if r.source_id not in topics or r.target_id not in topics: continue
        adjacency[r.source_id].append((r,r.target_id))
        if r.direction=='both': adjacency[r.target_id].append((r,r.source_id))
    queue=deque([(root,[],[root])]);candidates=[];expanded=0
    while queue and expanded<node_limit:
        current,hops,visited=queue.popleft();expanded+=1
        if len(hops)>=max_hops: continue
        for r,target in adjacency[current]:
            if len(candidates)>=node_limit:
                truncated=True;queue.clear();break
            if target in visited: continue
            new_hops=hops+[hop_json(r,current,target,topics)]
            ids=visited+[target]
            candidates.append({'topic_ids':ids,'relation_ids':[h['relation_id'] for h in new_hops],'hops':new_hops,'cross_discipline_count':sum(h['cross_discipline'] for h in new_hops)})
            queue.append((target,new_hops,ids))
    truncated=truncated or bool(queue)
    candidates.sort(key=lambda item:(-item['cross_discipline_count'],-len(item['hops']),item['topic_ids']))
    selected=[]
    for candidate in candidates:
        # Don't return every prefix of the same path as separate alternatives.
        if any(candidate['topic_ids']==prior['topic_ids'][:len(candidate['topic_ids'])] for prior in selected): continue
        selected.append(candidate)
        if len(selected)>=limit: break
    message='每一步都保留原始来源和关系类型。' if selected else '暂时没有可用的有据路径；不会补造连接。'
    if selected and max(len(p['hops']) for p in selected)<2: message='目前仅有一步可靠联系，后续路径资料不足。'
    return {'items':selected,'limited':truncated,'message':message,'search':{'expanded_nodes':expanded,'loaded_edges':len(rows),'node_limit':node_limit,'edge_limit':edge_limit}}


def validate_path(db,topic_ids,relation_ids,catalog=None):
    if len(topic_ids)!=len(relation_ids)+1 or len(set(topic_ids))!=len(topic_ids): raise ValueError('路径不连续或包含重复节点。')
    if catalog is None:
        topics={t.id:t for t in db.scalars(select(Topic).where(Topic.id.in_(topic_ids),Topic.content_status=='PUBLISHED'))}
        relations={r.id:r for r in db.scalars(select(TopicRelation).where(TopicRelation.id.in_(relation_ids)))}
    else:
        topics={tid:catalog[0][tid] for tid in topic_ids if tid in catalog[0] and catalog[0][tid].content_status=='PUBLISHED'}
        relations=catalog[1]
    if len(topics)!=len(topic_ids): raise ValueError('路径主题不存在或材料尚未准入。')
    hops=[]
    for a,b,rid in zip(topic_ids,topic_ids[1:],relation_ids):
        r=relations.get(rid)
        if not r or not reliable(r) or (r.source_id,r.target_id)!=(a,b) and not (r.direction=='both' and (r.target_id,r.source_id)==(a,b)):
            raise ValueError('关系方向、证据状态或路径连接不合格。')
        hops.append(hop_json(r,a,b,topics))
    return hops


def saved_json(db,path,catalog=None):
    fields={k:getattr(path,k) for k in ('id','title','topic_ids','relation_ids','position','created_at')}
    try:
        current=validate_path(db,path.topic_ids,path.relation_ids,catalog)
        changed=[h['fingerprint'] for h in current]!=[h['fingerprint'] for h in path.evidence_snapshot]
        fields.update(hops=current,available=True,evidence_changed=changed)
    except ValueError:
        fields.update(hops=path.evidence_snapshot,available=False,evidence_changed=True)
    return fields


def saved_paths_json(db,paths):
    paths=list(paths)
    if not paths: return []
    tids={tid for path in paths for tid in path.topic_ids};rids={rid for path in paths for rid in path.relation_ids}
    topics={t.id:t for t in db.scalars(select(Topic).where(Topic.id.in_(tids)))}
    relations={r.id:r for r in db.scalars(select(TopicRelation).where(TopicRelation.id.in_(rids)))}
    return [saved_json(db,path,(topics,relations)) for path in paths]
