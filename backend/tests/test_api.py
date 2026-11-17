from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func,text
from fastapi.testclient import TestClient
from app.models import *
from app.main import create_app
from app.services.discovery import create_batch


def test_health_openapi_profile_cookie(client):
    assert client.get('/api/health').json()['topics']==18
    r=client.get('/api/profile')
    assert r.status_code==200
    assert 'HttpOnly' in r.headers['set-cookie'] and 'SameSite=lax' in r.headers['set-cookie']
    p=r.json();assert p['id']==client.get('/api/profile').json()['id']
    assert 'token' not in str(p) and p['ai']['configured'] is False
    paths=client.get('/openapi.json').json()['paths']
    assert '/api/ai/chat' in paths and '/api/discover/impressions' in paths


def test_stable_batches_refresh_and_modes(client):
    a=client.get('/api/discover/today').json()
    assert len(a['items'])==5
    assert a['id']==client.get('/api/discover/today').json()['id']
    b=client.post('/api/discover/refresh',json={'mode':'unknown','idempotency_key':'refresh-0001'}).json()
    assert b['batch_number']==2 and b['parent_id']==a['id']
    assert b['id']==client.post('/api/discover/refresh',json={'mode':'unknown','idempotency_key':'refresh-0001'}).json()['id']
    broad=client.get('/api/discover/today?mode=broad').json()
    assert broad['id']!=b['id']
    assert client.get('/api/discover/today?mode=unknown').json()['id']==b['id']
    assert client.post('/api/discover/refresh',json={'mode':'broad','idempotency_key':'refresh-0001'}).status_code==409


def test_generation_not_exposure_visit_not_understanding(client,app):
    batch=client.get('/api/discover/today').json()
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(Impression))==0
        assert db.scalar(select(func.count()).select_from(TopicState))==0
    topic=batch['items'][0]['topic']['id']
    payload={'batch_id':batch['id'],'topic_ids':[topic]}
    assert client.post('/api/discover/impressions',json=payload).json()=={'recorded':1}
    assert client.post('/api/discover/impressions',json=payload).json()=={'recorded':0}
    detail=client.get('/api/topics/'+topic).json()
    assert detail['state']=={'bookmarked':False,'familiarity':'unknown','learning':'none','explored':True,'skipped_until':None}
    client.get('/api/topics/'+topic)
    assert client.get('/api/stats').json()['explored_count']==1
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(TopicEvent).where(TopicEvent.action=='visit'))==2
        assert db.scalar(select(func.count()).select_from(TopicEvent).where(TopicEvent.action=='explore'))==1


def test_bookmark_feedback_independent_persistence_and_event_dedupe(client,app):
    client.post('/api/bookmarks',json={'topic_id':'t0'})
    client.post('/api/bookmarks',json={'topic_id':'t0'})
    assert client.get('/api/bookmarks').json()['total']==1
    for action,key in [('unfamiliar','event-0001'),('learning','event-0002'),('understood','event-0003')]:
        assert client.post('/api/topics/t0/feedback',json={'action':action,'idempotency_key':key}).status_code==200
    client.post('/api/topics/t0/feedback',json={'action':'understood','idempotency_key':'event-0003'})
    state=client.get('/api/topics/t0').json()['state']
    assert state['bookmarked'] and state['familiarity']=='unfamiliar' and state['learning']=='understood'
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(TopicEvent).where(TopicEvent.action=='understood'))==1
    client.delete('/api/bookmarks/t0')
    assert client.get('/api/bookmarks').json()['total']==0
    assert client.get('/api/topics/t0').json()['state']['learning']=='understood'


def test_user_isolation_all_resources(client,app):
    client.post('/api/bookmarks',json={'topic_id':'t0'})
    client.get('/api/topics/t0')
    batch=client.get('/api/discover/today').json()
    with TestClient(app) as other:
        assert other.get('/api/stats').json()['explored_count']==0
        assert other.get('/api/bookmarks').json()['total']==0
        assert other.get('/api/discover/today').json()['id']!=batch['id']
        r=other.post('/api/discover/impressions',json={'batch_id':batch['id'],'topic_ids':['t0']})
        assert r.status_code==404
        assert other.patch('/api/profile',json={'user_id':client.get('/api/profile').json()['id']}).status_code==422


def test_invalid_no_write_and_rollback(client,app):
    client.get('/api/profile')
    with app.state.Session() as db: before=db.scalar(select(func.count()).select_from(TopicEvent))
    for body in ({'action':'mastered','idempotency_key':'invalid-000'},{'action':'known','idempotency_key':'x'}):
        assert client.post('/api/topics/t0/feedback',json=body).status_code==422
    assert client.post('/api/bookmarks',json={'topic_id':'does-not-exist'}).status_code==404
    assert client.patch('/api/profile',json={'timezone':'nope'}).status_code==422
    assert client.patch('/api/profile',json={'familiar_disciplines':['absent']}).status_code==422
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(TopicEvent))==before
        assert db.scalar(select(func.count()).select_from(Bookmark))==0
        try:
            db.add(Discipline(id='rollback',name='rollback',color='red'));db.flush()
            raise ValueError('deliberate test failure')
        except ValueError: db.rollback()
        assert db.get(Discipline,'rollback') is None


def test_error_and_origin_format(client):
    r=client.post('/api/bookmarks',json={'topic_id':'t0'},headers={'origin':'https://evil.example'})
    assert r.status_code==403 and r.json()['error']['code']=='ORIGIN_REJECTED'
    assert r.json()['error']['request_id']
    assert client.get('/api/missing').status_code==404
    assert client.get('/api/bookmarks?limit=10001').status_code==422


def test_settings_dont_silently_replace_batch(client):
    a=client.get('/api/discover/today').json()
    assert not a['settings_changed']
    client.patch('/api/profile',json={'familiar_disciplines':['d0'],'intensity':0.2,'broad_use_history':False})
    b=client.get('/api/discover/today').json()
    assert b['id']==a['id'] and b['settings_changed']


def test_date_and_timezone(client,app,monkeypatch):
    import app.services.discovery as discovery
    real_date=discovery.local_date
    monkeypatch.setattr(discovery,'local_date',lambda p:'2000-01-01')
    client.get('/api/discover/today')
    monkeypatch.setattr(discovery,'local_date',real_date)
    today=client.get('/api/discover/today').json()
    assert today['date']!='2000-01-01' and today['batch_number']==1
    assert client.patch('/api/profile',json={'timezone':'America/Los_Angeles'}).status_code==200
    from zoneinfo import ZoneInfo
    assert client.get('/api/discover/today').json()['date']==datetime.now(ZoneInfo('America/Los_Angeles')).date().isoformat()


def test_map_valid_edges_states_limits(client):
    client.get('/api/topics/t0')
    client.post('/api/bookmarks',json={'topic_id':'t0'})
    g=client.get('/api/map').json()
    ids={n['id'] for n in g['nodes']}
    assert all(e['source'] in ids and e['target'] in ids and e['type'] and e['explanation'] for e in g['edges'])
    node=next(n for n in g['nodes'] if n.get('topic_id')=='t0')
    assert node['explored'] and node['bookmarked']
    limited=client.get('/api/map?limit=5').json()
    assert len(limited['nodes'])<=5 and limited['truncated']
    explored=client.get('/api/map?scope=explored').json()
    assert sum(n['type']=='topic' for n in explored['nodes'])==1
    root=client.get('/api/map?root=topic:t0&depth=1').json()
    assert {n['topic_id'] for n in root['nodes'] if n['type']=='topic'}=={'t0','t1'}


def test_skip_expires_not_permanent(client,app):
    client.post('/api/topics/t0/feedback',json={'action':'skip','idempotency_key':'skip-0001'})
    pid=client.get('/api/profile').json()['id']
    from app.services.discovery import history_snapshot
    with app.state.Session() as db:
        p=db.get(Profile,pid)
        assert 't0' in history_snapshot(db,p)['skipped_ids']
        st=db.get(TopicState,(pid,'t0'));st.skipped_until='2000-01-01';db.commit()
        assert 't0' not in history_snapshot(db,p)['skipped_ids']


def test_reset_scope_and_no_key(client,app):
    client.get('/api/topics/t0')
    client.post('/api/bookmarks',json={'topic_id':'t0'})
    client.get('/api/discover/today')
    assert client.post('/api/ai/explain',json={'topic_id':'t0'}).json()['status']=='unavailable'
    assert client.post('/api/ai/chat',json={'topic_id':'t0','message':'解释一下'}).json()['status']=='unavailable'
    assert client.post('/api/profile/reset',json={'confirm':False}).status_code==422
    assert client.post('/api/profile/reset',json={'confirm':True}).json()['cleared']
    assert client.get('/api/stats').json()['explored_count']==0
    assert client.get('/api/bookmarks').json()['total']==0
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(Topic))==18
        assert db.scalar(select(func.count()).select_from(DailyRecommendation))==0
        assert db.scalar(select(func.count()).select_from(TopicEvent))==0


def test_restart_file_persists(client,app):
    client.get('/api/topics/t0');client.post('/api/bookmarks',json={'topic_id':'t0'})
    token=client.cookies.get('unknown_session')
    restarted=create_app(app.state.settings,initialize=False)
    with TestClient(restarted) as c:
        c.cookies.set('unknown_session',token)
        assert c.get('/api/bookmarks').json()['total']==1
        assert c.get('/api/stats').json()['explored_count']==1


def test_reproducible_snapshot(client,app):
    from app.recommendation import recommend
    b=client.get('/api/discover/today').json()
    with app.state.Session() as db:
        stored=db.get(DailyRecommendation,b['id'])
        snapshot=stored.snapshot
        replay=recommend(snapshot['candidates'],snapshot['history'],mode=stored.mode,seed=stored.seed)
        assert [i['topic_id'] for i in replay['items']]==[i['topic']['id'] for i in b['items']]


def _concurrent_requests(client, method, path, body=None, workers=4):
    """One known cookie, simultaneous submissions, separate response objects."""
    from threading import Barrier
    cookie = client.cookies.get('unknown_session')
    barrier = Barrier(workers)
    def perform(_):
        barrier.wait(timeout=10)
        return client.request(method, path, json=body, headers={'Cookie':f'unknown_session={cookie}'})
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(perform, range(workers)))


def test_concurrent_initial_batch_same_cookie_is_one_stable_result(client,app):
    profile_id=client.get('/api/profile').json()['id']
    responses=_concurrent_requests(client,'GET','/api/discover/today')
    assert [r.status_code for r in responses]==[200]*len(responses)
    assert len({r.json()['id'] for r in responses})==1
    assert client.get('/api/discover/today').json()['id']==responses[0].json()['id']
    with app.state.Session() as db:
        batches=list(db.scalars(select(DailyRecommendation).where(DailyRecommendation.profile_id==profile_id)))
        assert len(batches)==1
        assert db.scalar(select(func.count()).select_from(RecommendationItem).where(RecommendationItem.batch_id==batches[0].id))==5


def test_concurrent_refresh_idempotency_same_cookie(client,app):
    client.get('/api/profile')
    first=client.get('/api/discover/today').json()
    payload={'mode':'unknown','idempotency_key':'concurrent-refresh-0001'}
    responses=_concurrent_requests(client,'POST','/api/discover/refresh',payload)
    assert [r.status_code for r in responses]==[200]*len(responses)
    assert len({r.json()['id'] for r in responses})==1
    refreshed=responses[0].json()
    assert refreshed['batch_number']==2 and refreshed['parent_id']==first['id']
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(DailyRecommendation))==2
        assert db.scalar(select(func.count()).select_from(RecommendationItem))==10


def test_concurrent_bookmarks_and_feedback_are_idempotent(client,app):
    client.get('/api/profile')
    bookmarks=_concurrent_requests(client,'POST','/api/bookmarks',{'topic_id':'t0'})
    assert [r.status_code for r in bookmarks]==[200]*len(bookmarks)
    assert client.get('/api/bookmarks').json()['total']==1
    feedback=_concurrent_requests(client,'POST','/api/topics/t0/feedback',{'action':'understood','idempotency_key':'concurrent-feedback-0001'})
    assert [r.status_code for r in feedback]==[200]*len(feedback)
    assert client.get('/api/topics/t0').json()['state']['learning']=='understood'
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(Bookmark))==1
        assert db.scalar(select(func.count()).select_from(TopicEvent).where(TopicEvent.idempotency_key=='concurrent-feedback-0001'))==1


def test_recent_revisit_of_older_topic_keeps_discipline_out_of_long_unexplored(client,app):
    profile_id=client.get('/api/profile').json()['id']
    # t0 and t6 share d0. The newer first-explored topic has an old last visit;
    # the older first-explored topic was revisited today.
    client.get('/api/topics/t0');client.get('/api/topics/t6')
    with app.state.Session() as db:
        old=db.get(TopicState,(profile_id,'t0'))
        newer=db.get(TopicState,(profile_id,'t6'))
        old.first_explored_at='2000-01-01T00:00:00+00:00'
        old.last_visited_at=datetime.now(timezone.utc).isoformat()
        newer.first_explored_at='2001-01-01T00:00:00+00:00'
        newer.last_visited_at='2001-01-01T00:00:00+00:00'
        db.commit()
    statistics=client.get('/api/stats').json()
    assert 'd0' not in {item['id'] for item in statistics['long_unexplored_disciplines']}
