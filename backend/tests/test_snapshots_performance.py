import copy
import json
from sqlalchemy import select,func,event

from app.models import CatalogSnapshot,DailyRecommendation,Profile,Topic,TopicSource
from app.services.snapshots import load_snapshot,replay_batch
from app.recommendation.legacy_v1 import recommend as legacy_recommend
from app.services.discovery import candidate_snapshot


def test_shared_immutable_catalog_replays_unknown_broad_and_surprise(client,app):
    batches=[client.get('/api/discover/today?mode='+m).json() for m in ('unknown','bridge','broad')]
    client.patch('/api/profile',json={'broad_use_history':False})
    batches.append(client.post('/api/discover/refresh',json={'mode':'broad','idempotency_key':'broad-free-replay-001'}).json())
    app.state.settings.semantic_similarity=False
    draw=client.post('/api/discover/surprise',json={'strength':'gentle','history_free':True,'idempotency_key':'surprise-replay-001'}).json()
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(CatalogSnapshot))==1
        for batch in [*batches,draw]:
            stored=db.get(DailyRecommendation,batch['id'])
            assert stored.snapshot['format']==2 and 'candidates' not in stored.snapshot
            assert 'candidate_snapshot' not in stored.snapshot['result']
            loaded=load_snapshot(db,stored);replayed=replay_batch(db,stored)
            assert replayed['items']==loaded['result']['items']
            assert len(json.dumps(stored.snapshot))<len(json.dumps(loaded))
        original=db.scalar(select(CatalogSnapshot));payload=original.payload
        db.get(TopicSource,'s0').url='https://example.org/new-version';db.commit()
    client.post('/api/discover/refresh',json={'mode':'unknown','idempotency_key':'new-source-catalog-001'})
    with app.state.Session() as db:
        assert db.scalar(select(func.count()).select_from(CatalogSnapshot))==2
        assert db.get(CatalogSnapshot,original.id).payload==payload
        assert replay_batch(db,db.get(DailyRecommendation,batches[0]['id']))['items']==load_snapshot(db,db.get(DailyRecommendation,batches[0]['id']))['result']['items']


def test_legacy_inline_snapshot_dispatches_to_frozen_v1(client,app):
    batch=client.get('/api/discover/today').json()
    with app.state.Session() as db:
        stored=db.get(DailyRecommendation,batch['id']);snapshot=load_snapshot(db,stored)
        legacy=legacy_recommend(snapshot['candidates'],snapshot['history'],mode='unknown',seed=stored.seed)
        stored.strategy_version='unknown-rerank-1.0';stored.snapshot={'candidates':snapshot['candidates'],'history':snapshot['history'],'result':legacy};db.commit()
        assert replay_batch(db,stored)==legacy
        assert load_snapshot(db,stored)==stored.snapshot


def test_catalog_corruption_fails_closed_without_replaying_modified_inputs(client,app):
    batch=client.get('/api/discover/today').json()
    with app.state.Session() as db:
        stored=db.get(DailyRecommendation,batch['id']);catalog=db.get(CatalogSnapshot,stored.snapshot['catalog_ref']);catalog.payload=b'not zlib';db.commit()
        import pytest,zlib
        with pytest.raises((ValueError,zlib.error)): load_snapshot(db,stored)


def test_collection_and_candidate_loading_queries_are_bounded(client,app):
    for i in range(12): client.post('/api/bookmarks',json={'topic_id':f't{i}'})
    counts=[]
    def count(*_): counts.append(1)
    event.listen(app.state.engine,'before_cursor_execute',count)
    small=client.get('/api/bookmarks?limit=1');q1=len(counts);counts.clear()
    large=client.get('/api/bookmarks?limit=12');q12=len(counts);counts.clear()
    graph=client.get('/api/map');qg=len(counts);counts.clear()
    with app.state.Session() as db: candidates=candidate_snapshot(db)
    qc=len(counts)
    event.remove(app.state.engine,'before_cursor_execute',count)
    assert small.status_code==large.status_code==graph.status_code==200
    assert len(large.json()['items'])==12 and q12<=q1+1 and q12<=9
    assert qg<=9 and qc==2 and len(candidates)==18


def test_source_retraction_does_not_serve_unpublished_current_recommendations(client,app):
    batch=client.get('/api/discover/today').json();tid=batch['items'][0]['topic']['id']
    with app.state.Session() as db: db.get(Topic,tid).content_status='RAW';db.commit()
    current=client.get('/api/discover/today').json()
    assert current['id']==batch['id'] and tid not in [i['topic']['id'] for i in current['items']]
    assert 'CONTENT_CHANGED_SINCE_BATCH' in current['constraints']['reason_codes']
    with app.state.Session() as db:
        stored=db.get(DailyRecommendation,batch['id'])
        assert tid in [i['topic_id'] for i in replay_batch(db,stored)['items']]
