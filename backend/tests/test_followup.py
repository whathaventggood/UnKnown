from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.models import Profile, TopicState, TopicEvent, TopicRelation, RecommendationItem, DailyRecommendation
from app.services.discovery import history_snapshot


def mark(client, topic, action, key=None):
    r=client.post(f'/api/topics/{topic}/feedback',json={'action':action,'idempotency_key':key or f'followup-{topic}-{action}'})
    assert r.status_code==200
    return r.json()['state']


def test_learning_pagination_state_changes_and_bookmark_independence(client):
    for tid in ('t0','t1','t2','t3','t4'): mark(client,tid,'learning')
    client.post('/api/bookmarks',json={'topic_id':'t1'})
    pages=[client.get(f'/api/learning?limit=2&offset={offset}').json() for offset in (0,2,4,6)]
    assert all(p['total']==5 for p in pages)
    rows=[t for p in pages for t in p['items']]
    assert [t['id'] for t in rows]==['t0','t1','t2','t3','t4']
    assert rows[1]['state']['bookmarked']
    assert not any(t['state']['explored'] for t in rows)
    mark(client,'t1','understood')
    assert client.get('/api/learning').json()['total']==4
    understood=client.get('/api/learning?status=understood').json()
    assert understood['total']==1 and understood['items'][0]['state']['bookmarked']
    mark(client,'t1','none')
    assert client.get('/api/learning?status=understood').json()['total']==0
    assert client.get('/api/bookmarks').json()['total']==1
    for query in ('status=mastered','limit=0','offset=-1'):
        assert client.get('/api/learning?'+query).status_code==422


def test_learning_and_skip_isolated_by_cookie(client,app):
    mark(client,'t0','learning');mark(client,'t0','skip')
    with TestClient(app, headers={'X-Unknown-Request':'1'}) as other:
        assert other.get('/api/learning').json()=={'items':[],'total':0}
        assert other.get('/api/topics/t0').json()['state']['skipped_until'] is None
        mark(other,'t0','unskip')
    assert client.get('/api/learning').json()['total']==1
    assert client.get('/api/learning').json()['items'][0]['state']['skipped_until']


def test_skip_expiry_idempotence_and_real_undo_do_not_create_exploration(client,app):
    mark(client,'t0','unfamiliar');mark(client,'t0','learning')
    batch=client.get('/api/discover/today').json()
    start=datetime.now(timezone.utc)
    skipped=mark(client,'t0','skip')
    assert timedelta(days=2, hours=23)<datetime.fromisoformat(skipped['skipped_until'])-start<timedelta(days=3,minutes=1)
    assert mark(client,'t0','skip')['skipped_until']==skipped['skipped_until']
    restored=client.get('/api/learning').json()['items'][0]['state']
    assert restored==skipped
    pid=client.get('/api/profile').json()['id']
    with app.state.Session() as db:
        p=db.get(Profile,pid)
        assert 't0' in history_snapshot(db,p)['skipped_ids']
        db.get(TopicState,(pid,'t0')).skipped_until='2000-01-01T00:00:00+00:00';db.commit()
        assert 't0' not in history_snapshot(db,p)['skipped_ids']
    undo=mark(client,'t0','unskip')
    assert undo=={'bookmarked':False,'familiarity':'unfamiliar','learning':'learning','explored':False,'skipped_until':None}
    assert mark(client,'t0','unskip')==undo
    assert client.get('/api/discover/today').json()['id']==batch['id']
    assert client.get('/api/stats').json()['explored_count']==0
    with app.state.Session() as db:
        assert not list(db.scalars(select(TopicEvent).where(TopicEvent.action.in_(['visit','explore']))))
        assert 't0' not in history_snapshot(db,db.get(Profile,pid))['skipped_ids']


def test_relation_endpoints_keep_direction_from_both_sides(client):
    a=client.get('/api/topics/t0/related').json()['items'][0]['relation']
    b=client.get('/api/topics/t1/related').json()['items'][0]['relation']
    assert a==b
    assert (a['source_id'],a['source_title'],a['target_id'],a['target_title'])==('t0','测试主题0','t1','测试主题1')
    assert a['direction']=='forward' and a['source_url']


def test_legacy_bridge_names_enriched_without_rewriting_snapshot(client,app):
    batch=client.get('/api/discover/today?mode=bridge').json()
    legacy=[{'from_id':'t0','to_id':'t1','type':'teaching','label':'测试关系','explanation':'测试','source_url':'https://example.org/evidence','direction':'forward'}]
    with app.state.Session() as db:
        item=db.scalar(select(RecommendationItem).where(RecommendationItem.batch_id==batch['id']))
        item.bridge_path=legacy
        snapshot=db.get(DailyRecommendation,batch['id']).snapshot
        target=item.topic_id;db.commit()
    result=client.get('/api/discover/today?mode=bridge').json()
    hop=next(i for i in result['items'] if i['topic']['id']==target)['bridge_path'][0]
    assert hop['from_title']=='测试主题0' and hop['to_title']=='测试主题1'
    with app.state.Session() as db:
        assert db.get(DailyRecommendation,batch['id']).snapshot==snapshot
        assert db.get(RecommendationItem,(batch['id'],target)).bridge_path==legacy


def test_map_root_survives_dense_neighborhood_budget(client,app):
    with app.state.Session() as db:
        for i in range(17): db.add(TopicRelation(source_id='t17',target_id=f't{i}',type='teaching',label='测试',explanation='测试',source_url='https://example.org/evidence'))
        db.commit()
    graph=client.get('/api/map?root=topic:t17&limit=5').json()
    assert any(n['id']=='topic:t17' for n in graph['nodes'])
    ids={n['id'] for n in graph['nodes']}
    assert len(ids)<=5 and all(e['source'] in ids and e['target'] in ids for e in graph['edges'])
    assert client.get('/api/map?root=topic:missing').json()['nodes']==[]
