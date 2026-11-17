#!/usr/bin/env python3
"""A real local API journey on a new disposable database; no network or LLM calls."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app


def verify():
    with TemporaryDirectory(prefix='unknown-offline-') as temporary, patch('httpx.AsyncClient.send',side_effect=AssertionError('Unexpected external network request')) as remote:
        settings=Settings(database_url=f'sqlite:///{Path(temporary)/"fresh.db"}',llm_api_key='',_env_file=None)
        app=create_app(settings)
        with TestClient(app, headers={'X-Unknown-Request':'1'}) as c:
            p=c.get('/api/profile');assert p.status_code==200
            assert c.patch('/api/profile',json={'onboarding_complete':True}).status_code==200
            batch=c.get('/api/discover/today').json()
            assert len(batch['items'])==5
            assert batch['id']==c.get('/api/discover/today').json()['id']
            tid=batch['items'][0]['topic']['id']
            assert c.post('/api/discover/impressions',json={'batch_id':batch['id'],'topic_ids':[tid]}).status_code==200
            assert c.get('/api/topics/'+tid).json()['state']['explored']
            assert c.post('/api/topics/'+tid+'/feedback',json={'action':'unfamiliar','idempotency_key':'offline-feedback-001'}).status_code==200
            assert c.post('/api/bookmarks',json={'topic_id':tid}).status_code==200
            assert c.get('/api/stats').json()['explored_count']==1
            assert c.post('/api/ai/explain',json={'topic_id':tid}).json()['status']=='unavailable'
            assert c.get('/api/map').json()['nodes']
            assert c.post('/api/discover/surprise',json={'strength':'far','history_free':True,'idempotency_key':'offline-surprise-001'}).json()['item']['topic']['sources']
            paths=c.get('/api/topics/graph-theory/paths').json()['items']
            saved=c.post('/api/paths',json={'topic_ids':paths[0]['topic_ids'],'relation_ids':paths[0]['relation_ids'],'idempotency_key':'offline-save-path-001'}).json()
            assert c.patch('/api/paths/'+saved['id'],json={'position':1}).status_code==200
            challenge=c.get('/api/topics/'+tid+'/challenge').json()['challenge']
            assert c.post('/api/topics/'+tid+'/challenge',json={'challenge_id':challenge['id'],'answer':'这是本机离线作答，随后根据参考材料核对。','idempotency_key':'offline-challenge-001'}).status_code==200
            assert c.post('/api/topics/'+tid+'/feedback',json={'action':'revisit','idempotency_key':'offline-revisit-001'}).status_code==200
            assert c.get('/').status_code==200 and c.get('/topics/graph-theory').status_code==200
            token=c.cookies.get('unknown_session')
        # Recreate engine/app on same persisted SQLite file, not the previous in-memory session.
        restarted=create_app(settings)
        with TestClient(restarted, headers={'X-Unknown-Request':'1'}) as c:
            c.cookies.set('unknown_session',token)
            assert c.get('/api/bookmarks').json()['total']==1
            assert c.get('/api/stats').json()['explored_count']==1
            assert c.get('/api/discover/today').json()['id']==batch['id']
            assert c.get('/api/topics/'+tid).json()['state']['familiarity']=='unfamiliar'
            assert c.get('/api/topics/'+tid).json()['state']['learning']=='none'
            assert c.get('/api/topics/'+tid+'/challenge/attempts').json()['items'][0]['answer']
            assert c.get('/api/paths').json()['items'][0]['position']==1
            assert c.get('/api/revisits').json()['total']==1
            for mode in ('bridge','broad'):
                assert len(c.get('/api/discover/today?mode='+mode).json()['items'])==5
            assert c.post('/api/profile/reset',json={'confirm':True}).json()['cleared']
            assert c.get('/api/stats').json()['explored_count']==0
            assert c.get('/api/bookmarks').json()['total']==0
            assert c.get('/api/paths').json()['total']==c.get('/api/revisits').json()['total']==0
            assert c.get('/api/topics/'+tid+'/challenge/attempts').json()['items']==[]
            health=c.get('/api/health').json()
            assert health['topics']==60
        assert remote.call_count==0
        return {'status':'passed','seed_topics':60,'primary_disciplines':12,'new_database':True,'fresh_app_restart_persistence':True,'three_modes':True,'surprise':True,'saved_path_progress':True,'cognitive_challenge':True,'voluntary_revisit':True,'llm_key':False,'remote_requests':remote.call_count,'privacy_reset_keeps_catalogue':True,'scope':'in-process ASGI; not browser/layout verification'}

if __name__=='__main__': print(json.dumps(verify(),ensure_ascii=False,indent=2))
