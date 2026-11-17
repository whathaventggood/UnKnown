import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app,migrate
from app.services.catalog import upsert_seed

@pytest.fixture
def catalog():
    # Deliberately synthetic test fixtures; never imported into the product seed catalog.
    return {'disciplines':[{'id':f'd{i}','name':f'测试学科{i}','color':'#397d77','description':'synthetic'} for i in range(6)],'topics':[{'id':f't{i}','title':f'测试主题{i}','summary':'这是用于验证行为的合成测试摘要。不是产品数据。','original_summary':'Synthetic evidence for testing.','language':'en','primary_discipline_id':f'd{i%6}','subfield':f'sub{i}','question':'这是如何工作的？','value':'测试用途','quality_score':0.8,'quality_features':{'has_example':True,'source_traceable':True},'sources':[{'id':f's{i}','platform':'test','external_id':f'x{i}','url':f'https://example.org/testing/{i}','title':f'Test{i}','language':'en','license':'test-only','excerpt':'Synthetic evidence for testing.','content_hash':f'h{i}'}]} for i in range(18)],'relations':[{'id':'r1','source_id':'t0','target_id':'t1','type':'teaching','label':'教学联系','explanation':'测试关系','source_url':'https://example.org/test/relationship'}]}

@pytest.fixture
def app(tmp_path,catalog):
    settings=Settings(database_url=f'sqlite:///{tmp_path}/test.db',_env_file=None)
    app=create_app(settings,initialize=False)
    migrate(settings)
    with app.state.Session() as db: upsert_seed(db,catalog);db.commit()
    return app

@pytest.fixture
def client(app):
    with TestClient(app, headers={'X-Unknown-Request':'1'}) as c: yield c
