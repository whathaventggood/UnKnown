import json
from datetime import datetime,timedelta,timezone
from fastapi.testclient import TestClient
from sqlalchemy import select,insert,event

from app.core.config import ROOT
from app.models import Topic,TopicSource,TopicRelation,Profile,TopicState,ChallengeAttempt,SavedPath
from app.services.catalog import upsert_seed
from app.services.paths import paths_from


def real_catalog(app):
    with app.state.Session() as db:
        upsert_seed(db,json.loads((ROOT/'data/seeds/topics.json').read_text()));db.commit()


def test_real_cross_discipline_path_save_reopen_progress_and_isolation(client,app):
    real_catalog(app)
    result=client.get('/api/topics/graph-theory/paths').json()
    path=result['items'][0]
    assert path['topic_ids']==['graph-theory','social-network','social-capital','public-good']
    assert all(h['source_url'].startswith('https://en.wikipedia.org/') for h in path['hops'])
    assert path['hops'][0]['cross_discipline'] and path['hops'][0]['type']=='fact'
    assert client.get('/api/paths').json()['total']==0
    body={'topic_ids':path['topic_ids'],'relation_ids':path['relation_ids'],'idempotency_key':'save-real-path-001'}
    saved=client.post('/api/paths',json=body).json()
    assert saved['available'] and not saved['evidence_changed']
    assert client.post('/api/paths',json=body).json()['id']==saved['id']
    assert client.patch('/api/paths/'+saved['id'],json={'position':2}).json()['position']==2
    assert client.get('/api/paths/'+saved['id']).json()['position']==2
    assert client.get('/api/stats').json()['feedback_metrics']['saved_path_continuation_ratio']==1
    with TestClient(app,headers={'X-Unknown-Request':'1'}) as other:
        assert other.get('/api/paths').json()['items']==[]
        assert other.get('/api/paths/'+saved['id']).status_code==404
        assert other.delete('/api/paths/'+saved['id']).status_code==404


def test_invalid_direction_cycles_pending_edges_and_evidence_changes(client,app):
    real_catalog(app)
    invalid={'topic_ids':['social-network','graph-theory'],'relation_ids':['graph-theory--social-network'],'idempotency_key':'reverse-path-001'}
    assert client.post('/api/paths',json=invalid).status_code==422
    cyclic={**invalid,'topic_ids':['graph-theory','social-network','graph-theory'],'relation_ids':['graph-theory--social-network']*2}
    assert client.post('/api/paths',json=cyclic).status_code==422
    path=client.get('/api/topics/graph-theory/paths').json()['items'][0]
    saved=client.post('/api/paths',json={k:path[k] for k in ('topic_ids','relation_ids')}|{'idempotency_key':'changed-path-001'}).json()
    with app.state.Session() as db:
        r=db.get(TopicRelation,'graph-theory--social-network');r.explanation+=' 来源说明已更新。';db.commit()
    assert client.get('/api/paths/'+saved['id']).json()['evidence_changed']
    with app.state.Session() as db:
        db.get(TopicRelation,'graph-theory--social-network').evidence_status='pending';db.commit()
    assert client.get('/api/paths/'+saved['id']).json()['available'] is False
    assert client.get('/api/topics/graph-theory/paths').json()['items']==[]
    assert client.get('/api/topics/graph-theory/related').json()['items']==[]


def test_offline_challenge_answer_survives_refresh_never_proves_mastery(client,app):
    real_catalog(app)
    initial=client.get('/api/topics/graph-theory/challenge').json()['challenge']
    assert initial['reference_answer'] is None and initial['key_points']==[]
    body={'challenge_id':initial['id'],'answer':'节点代表站点，边表示直达关系。是否连边取决于问题。','idempotency_key':'graph-answer-001'}
    answered=client.post('/api/topics/graph-theory/challenge',json=body)
    assert answered.status_code==200
    result=answered.json()
    assert result['feedback']['score'] is None and result['feedback']['ai_used'] is False
    assert result['feedback']['reference']['sources']
    assert client.post('/api/topics/graph-theory/challenge',json=body).json()['id']==result['id']
    assert client.patch('/api/challenge-attempts/'+result['id'],json={'self_assessment':'partial'}).json()['self_assessment']=='partial'
    assert client.get('/api/topics/graph-theory/challenge/attempts').json()['items'][0]['answer']==body['answer']
    assert client.get('/api/topics/graph-theory').json()['state']['learning']=='none'
    with TestClient(app,headers={'X-Unknown-Request':'1'}) as other:
        assert other.get('/api/topics/graph-theory/challenge/attempts').json()['items']==[]
        assert other.patch('/api/challenge-attempts/'+result['id'],json={'self_assessment':'got_it'}).status_code==404


def test_challenge_source_change_rejects_stale_question_without_saving(client,app):
    initial=client.get('/api/topics/t0/challenge').json()['challenge']
    with app.state.Session() as db:
        db.get(TopicSource,'s0').excerpt='New source passage with changed evidence.';db.commit()
    body={'challenge_id':initial['id'],'answer':'旧材料下的回答','idempotency_key':'changed-answer-001'}
    response=client.post('/api/topics/t0/challenge',json=body)
    assert response.status_code==409 and response.json()['error']['code']=='CHALLENGE_CHANGED'
    assert client.get('/api/topics/t0/challenge/attempts').json()['items']==[]


def test_revisit_is_opt_in_cancellable_and_reset_keeps_shared_material(client,app):
    assert client.get('/api/revisits').json()['items']==[]
    client.post('/api/topics/t0/feedback',json={'action':'revisit','idempotency_key':'want-revisit-001'})
    assert client.get('/api/revisits').json()['total']==1
    assert client.get('/api/revisits?due_only=true').json()['total']==0
    pid=client.get('/api/profile').json()['id']
    with app.state.Session() as db:
        db.get(TopicState,(pid,'t0')).revisit_at=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat();db.commit()
    assert client.get('/api/revisits?due_only=true').json()['total']==1
    client.post('/api/topics/t0/feedback',json={'action':'cancel_revisit','idempotency_key':'cancel-revisit-001'})
    assert client.get('/api/revisits').json()['total']==0
    challenge=client.get('/api/topics/t0/challenge').json()['challenge']
    client.post('/api/topics/t0/challenge',json={'challenge_id':challenge['id'],'answer':'测试回答','idempotency_key':'clear-answer-001'})
    assert client.post('/api/profile/reset',json={'confirm':True}).status_code==200
    with app.state.Session() as db:
        assert list(db.scalars(select(ChallengeAttempt)))==[] and list(db.scalars(select(SavedPath)))==[]
        assert db.get(Topic,'t0') and db.get(TopicSource,'s0')
    metrics=client.get('/api/stats').json()['feedback_metrics']
    assert metrics['self_reported_unfamiliar_ratio'] is None and metrics['self_reported_worthwhile_ratio'] is None and metrics['challenge_correctness_ratio'] is None


def test_sparse_and_large_dense_graph_have_global_budgets_and_bounded_queries(app):
    with app.state.Session() as db:
        topics=[{'id':f'g{i}','title':f'隔离图测试{i}','primary_discipline_id':'d0','content_status':'PUBLISHED'} for i in range(300)]
        db.execute(insert(Topic),topics)
        edges=[{'id':f'chain{i}','source_id':f'g{i}','target_id':f'g{i+1}','type':'fact','label':'合成测试','explanation':'仅隔离图测试，不是产品关系','source_url':'https://example.org/synthetic','direction':'forward','evidence_status':'curated'} for i in range(299)]
        db.execute(insert(TopicRelation),edges);db.commit()
        sparse=paths_from(db,'g0')
        assert len(sparse['items'][0]['hops'])==4
        dense=[{'id':f'dense-{i}-{j}','source_id':f'g{i}','target_id':f'g{j}','type':'fact','label':'合成测试','explanation':'仅隔离图测试','source_url':'https://example.org/synthetic','direction':'forward','evidence_status':'curated'} for i in range(100) for j in range(100,200)]
        db.execute(insert(TopicRelation),dense);db.commit()
        counter=[0]
        def count(*_): counter[0]+=1
        event.listen(app.state.engine,'before_cursor_execute',count)
        result=paths_from(db,'g0',node_limit=50,edge_limit=200)
        event.remove(app.state.engine,'before_cursor_execute',count)
        assert result['limited'] and len(result['items'])<=3 and counter[0]<=6
        assert result['search']['expanded_nodes']<=50 and result['search']['loaded_edges']<=200
        assert all(len(p['topic_ids'])==len(set(p['topic_ids'])) for p in result['items'])
