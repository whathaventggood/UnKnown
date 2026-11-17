import json
from pathlib import Path
from contextlib import asynccontextmanager
from uuid import uuid4
import logging
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import JSONResponse,FileResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from app.core.config import Settings,ROOT
from app.core.database import make_engine,session_factory
from app.api.routes import router
from app.services.catalog import upsert_seed
from app.ai.service import AIService
from app.ai.provider import CompatibleProvider,ProviderError


def migrate(settings):
    from alembic import command
    from alembic.config import Config
    import os
    # Alembic env reads explicit URL; no mutation of process environment.
    cfg=Config(str(ROOT/'backend/alembic.ini'))
    cfg.attributes['database_url']=settings.database_url
    command.upgrade(cfg,'head')


def create_app(settings=None,initialize=True,provider=None):
    settings=settings or Settings()
    if settings.database_url.startswith('sqlite:///'):
        path=settings.database_url.removeprefix('sqlite:///')
        if path!=':memory:': Path(path).expanduser().resolve().parent.mkdir(parents=True,exist_ok=True)
    engine=make_engine(settings.database_url)
    factory=session_factory(engine)
    @asynccontextmanager
    async def lifespan(app):
        if initialize:
            migrate(settings)
            seed_path=ROOT/'data/seeds/topics.json'
            if not seed_path.exists(): raise RuntimeError('Seed catalog missing; read README initialization')
            with factory() as db:
                upsert_seed(db,json.loads(seed_path.read_text()));db.commit()
        client=httpx.AsyncClient(timeout=settings.llm_timeout_seconds,follow_redirects=False,trust_env=settings.llm_trust_env)
        app.state.ai=AIService(settings,factory,provider or CompatibleProvider(settings,client))
        yield
        await client.aclose();engine.dispose()
    app=FastAPI(title='UnKnown · AI 认知破壁机',version='0.1.0',lifespan=lifespan)
    app.state.settings=settings;app.state.engine=engine;app.state.Session=factory
    app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins,allow_credentials=True,allow_methods=['GET','POST','PATCH','DELETE'],allow_headers=['Content-Type','X-Request-ID','X-Unknown-Request'])
    @app.middleware('http')
    async def guard(request,call_next):
        request.state.request_id=uuid4().hex
        # All private API reads require a non-simple header too: detail/today GETs
        # persist visits/batches. Forms, images and top-level navigations cannot set it.
        # Missing Origin is not authentication: CLI clients still need the header.
        origin=request.headers.get('origin')
        same=settings.public_origin or f'{request.url.scheme}://{request.url.netloc}'
        allowed={same,*settings.cors_origins}
        private=request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/disciplines')
        if private and request.method!='OPTIONS':
            if origin and origin not in allowed:
                return error_response(request,403,'ORIGIN_REJECTED','请求来源不在允许范围内。')
            referer=request.headers.get('referer')
            if not origin and referer:
                parsed=urlsplit(referer)
                if f'{parsed.scheme}://{parsed.netloc}' not in allowed:
                    return error_response(request,403,'ORIGIN_REJECTED','请求来源不在允许范围内。')
            if request.headers.get('sec-fetch-site')=='cross-site' and origin not in allowed:
                return error_response(request,403,'ORIGIN_REJECTED','跨站请求缺少可信来源。')
            if request.headers.get('x-unknown-request')!='1':
                return error_response(request,403,'CSRF_HEADER_REQUIRED','请通过应用发起请求；API 需要 X-Unknown-Request: 1。')
            if request.method in ('POST','PATCH') and request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json':
                return error_response(request,415,'JSON_REQUIRED','此接口只接受 application/json。')
        response=await call_next(request)
        if private: response.headers['Cache-Control']='no-store'
        response.headers['X-Request-ID']=request.state.request_id
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        return response
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request,exc):
        detail=exc.detail if isinstance(exc.detail,dict) else {'code':'HTTP_ERROR','message':str(exc.detail)}
        return error_response(request,exc.status_code,detail.get('code','HTTP_ERROR'),detail.get('message','请求未完成。'))
    @app.exception_handler(RequestValidationError)
    async def validation(request,exc): return error_response(request,422,'VALIDATION_ERROR','提交内容不符合要求，请检查字段和取值。')
    @app.exception_handler(IntegrityError)
    async def integrity(request,exc): return error_response(request,409,'CONCURRENT_CONFLICT','操作冲突，请重新读取当前结果后重试。')
    @app.exception_handler(ProviderError)
    async def provider_error(request,exc):
        return error_response(request,429 if exc.code in ('AI_BUDGET','AI_RATE_LIMITED') else 504 if exc.code=='AI_TIMEOUT' else 409 if exc.code=='AI_HISTORY_RESET' else 422 if exc.code=='AI_NO_EVIDENCE' else 502,exc.code,exc.message)
    @app.exception_handler(Exception)
    async def unexpected(request,exc):
        # Deliberately no request content, token, provider response or key in logs.
        logging.getLogger('unknown').error('request_failed type=%s request_id=%s',type(exc).__name__,getattr(request.state,'request_id','unknown'))
        return error_response(request,500,'INTERNAL_ERROR','服务暂时出错，请稍后重试。')
    app.include_router(router)
    dist=ROOT/'frontend/dist'
    @app.get('/{path:path}',include_in_schema=False)
    async def frontend(path:str):
        if path.startswith('api/'): raise HTTPException(404,detail={'code':'NOT_FOUND','message':'接口不存在。'})
        resolved=(dist/path).resolve()
        if resolved.is_relative_to(dist.resolve()) and resolved.is_file(): return FileResponse(resolved)
        if (dist/'index.html').exists(): return FileResponse(dist/'index.html')
        return {'message':'UnKnown API is running. Start frontend at http://127.0.0.1:5173; see README.'}
    return app


def error_response(request,status,code,message):
    return JSONResponse(status_code=status,content={'error':{'code':code,'message':message,'request_id':getattr(request.state,'request_id','unknown')}})

app=create_app()
