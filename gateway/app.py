"""Optional local gateway. No documents or access tokens are stored on the chain."""
from contextlib import asynccontextmanager
import hashlib
import io
import json
import secrets
import sqlite3
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI,Header,HTTPException
from fastapi.responses import HTMLResponse,Response,JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel,ConfigDict,Field
from node.app import BodyLimit
from node.schemas import VerifyRequest
from .grants import GrantStore,GrantDenied

class Issue(VerifyRequest):
    ttl_seconds:int=Field(default=300,ge=60,le=3600)

class Access(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    token:str=Field(pattern=r'^[A-Za-z0-9_-]{43}$')

SCRIPT="""const raw=location.hash.slice(1);history.replaceState(null,'','/');
const view=document.getElementById('result');
if(!/^[A-Za-z0-9_-]{43}$/.test(raw)){view.textContent='Acceso no disponible';}
else fetch('/access/resolve',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({token:raw}),cache:'no-store',credentials:'omit'})
.then(async r=>{const data=await r.json();view.textContent=r.ok?JSON.stringify(data,null,2):'Acceso no disponible';})
.catch(()=>{view.textContent='Servicio no disponible';});"""

def loopback_url(value):
    p=urlsplit(value)
    if p.scheme!='http' or p.hostname!='127.0.0.1' or not p.port or p.username or p.password or p.query or p.fragment or p.path not in ('','/'):
        raise ValueError('This gateway version allows loopback URLs only')
    return f'http://127.0.0.1:{p.port}'

def create_gateway(database,node_url,public_url,admin_key):
    node_url=loopback_url(node_url); public_url=loopback_url(public_url)
    if not isinstance(admin_key,str) or len(admin_key)<32: raise ValueError('Provide an independent admin secret of at least 32 characters')
    @asynccontextmanager
    async def lifespan(app):
        app.state.grants=GrantStore(database)
        async with httpx.AsyncClient(timeout=2,follow_redirects=False,trust_env=False) as client:
            app.state.client=client
            yield
    app=FastAPI(title='TFI synthetic QR access',version='0.1.0',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.add_middleware(BodyLimit)
    @app.middleware('http')
    async def secure_headers(request,call_next):
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer',
            'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"})
        return response
    @app.exception_handler(RequestValidationError)
    async def invalid_schema(request,exc):
        return JSONResponse({'detail':'invalid request'},status_code=422)  # Never echo a submitted token.
    @app.exception_handler(sqlite3.DatabaseError)
    async def bad_storage(request,exc):
        return JSONResponse({'detail':'access storage unavailable'},status_code=503)
    def admin(value):
        supplied=value.removeprefix('Bearer ') if value and value.startswith('Bearer ') else ''
        if not secrets.compare_digest(supplied.encode(),admin_key.encode()): raise HTTPException(401,'unauthorized')
    async def verify(reference):
        try:
            async with app.state.client.stream('POST',node_url+'/documents/verify',json=reference) as response:
                response.raise_for_status(); raw=bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw)>1024*1024: raise ValueError('response limit')
                result=json.loads(raw)
                if result.get('integrity')!='MATCH' or result.get('chain_valid') is not True:
                    raise HTTPException(409,'document is not confirmed on the current valid chain')
                return result
        except (httpx.HTTPError,ValueError,TypeError) as exc:
            raise HTTPException(503,'verification service unavailable') from exc
    @app.get('/healthz')
    def health(): return {'status':'ok','scope':'synthetic metadata only'}
    @app.get('/',response_class=HTMLResponse)
    def landing():
        return '<!doctype html><html lang="es"><meta charset="utf-8"><title>TFI · Verificación sintética</title><h1>Verificación de integridad</h1><p>Solo metadatos sintéticos. Sin certificación legal.</p><pre id="result">Verificando…</pre><script src="/client.js" defer></script></html>'
    @app.get('/client.js')
    def client_script(): return Response(SCRIPT,media_type='application/javascript')
    @app.post('/grants',status_code=201)
    async def issue(body:Issue,authorization:str|None=Header(default=None)):
        admin(authorization)
        reference=body.model_dump(exclude={'ttl_seconds'})
        await verify(reference)
        grant=app.state.grants.issue(**reference,ttl=body.ttl_seconds)
        url=public_url+'/#'+grant.pop('token')
        # SVG from the real QR encoder. No externally hosted QR generation service.
        import qrcode
        from qrcode.image.svg import SvgPathImage
        image=qrcode.make(url,image_factory=SvgPathImage)
        buffer=io.BytesIO(); image.save(buffer)
        return {**grant,'url':url,'qr_svg':buffer.getvalue().decode(),'synthetic_only':True}
    @app.delete('/grants/{grant_id}',status_code=204)
    def revoke(grant_id:str,authorization:str|None=Header(default=None)):
        admin(authorization)
        try: found=app.state.grants.revoke(grant_id)
        except ValueError: raise HTTPException(422,'invalid grant id') from None
        if not found: raise HTTPException(404,'grant not found')
        return Response(status_code=204)
    @app.post('/access/resolve')
    async def resolve(body:Access):
        try: reference=app.state.grants.resolve(body.token)
        except GrantDenied: raise HTTPException(403,'access unavailable') from None
        receipt=await verify(reference)
        return {'synthetic_only':True,'verification':receipt,
                'limitation':'Access to this gateway only; does not hide public blockchain metadata or revoke downloaded copies'}
    return app
