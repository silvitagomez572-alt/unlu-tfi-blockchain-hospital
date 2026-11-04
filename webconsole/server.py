from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import time
from typing import Literal
import httpx
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from blockchain.difficulty import next_difficulty
from blockchain.validation import validate_chain
from node.persistence import parse_chain
from documents.rules import fixture_bytes, fixture_hash, project

STATIC = Path(__file__).with_name('static')


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['register', 'version', 'event', 'mine', 'sync', 'verify', 'qr_create', 'qr_read', 'qr_revoke']
    role: Literal['mesa', 'direccion', 'legal', 'bio', 'auditor', 'operator']
    payload: dict = Field(default_factory=dict)


def install_console(app, settings, credentials):
    host = f'127.0.0.1:{settings.port}'
    origin = 'http://' + host
    session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    requests = deque()
    last_mining = None
    routes = {'register': '/documents/register', 'version': '/documents/versions',
              'event': '/documents/events', 'mine': '/mine', 'sync': '/peers/sync',
              'verify': '/documents/verify', 'qr_create': '/qr/create'}
    headers = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
               'X-Content-Type-Options': 'nosniff',
               'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}

    def gate(request, api=False):
        if request.headers.get('host') != host:
            raise HTTPException(403, 'local host required')
        entry_navigation = (not api and request.method == 'GET' and request.url.path in ('/console', '/console/')
                            and request.headers.get('sec-fetch-mode') == 'navigate'
                            and request.headers.get('sec-fetch-dest') == 'document')
        if request.headers.get('sec-fetch-site') == 'cross-site' and not entry_navigation:
            raise HTTPException(403, 'cross-site access denied')
        supplied_origin = request.headers.get('origin')
        if supplied_origin is not None and supplied_origin != origin:
            raise HTTPException(403, 'origin denied')
        if api:
            cookie, supplied = request.cookies.get('hisjb_session', ''), request.headers.get('x-hisjb-csrf', '')
            if not secrets.compare_digest(cookie.encode(), session.encode()) or not secrets.compare_digest(supplied.encode(), csrf.encode()):
                raise HTTPException(403, 'local session required; reload console')
            now = time.monotonic()
            while requests and now-requests[0] >= 60:
                requests.popleft()
            if len(requests) >= 240:
                raise HTTPException(429, 'console rate limit')
            requests.append(now)

    async def backend(method, path, role='auditor', payload=None):
        # Reuse the real routes and policy, not a second implementation of the node.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=origin,
                                    timeout=5, trust_env=False) as client:
            response = await client.request(method, path, json=payload,
                headers={'Authorization': 'Bearer '+credentials[role]})
            data = response.json() if response.content else None
            return response.status_code, data

    @app.get('/console', include_in_schema=False)
    def redirect(request: Request):
        gate(request)
        return RedirectResponse('/console/')

    @app.get('/console/', include_in_schema=False)
    def index(request: Request):
        gate(request)
        html = (STATIC/'index.html').read_text(encoding='utf-8').replace('__CSRF__', csrf)
        response = HTMLResponse(html, headers=headers)
        response.set_cookie('hisjb_session', session, httponly=True, samesite='strict', path='/console', max_age=3600)
        return response

    @app.get('/console/assets/{name}', include_in_schema=False)
    def asset(name: str, request: Request):
        gate(request)
        if name not in ('app.js', 'style.css'):
            raise HTTPException(404, 'asset not found')
        return Response((STATIC/name).read_bytes(), media_type='text/javascript' if name.endswith('.js') else 'text/css', headers=headers)

    @app.get('/console/api/summary', include_in_schema=False)
    def summary(request: Request):
        gate(request, True)
        state = app.state.node
        with state.lock:
            chain, pending = state.snapshot()
            validation = validate_chain(chain, state.config)
            project(chain, settings.actors, state.config)
            data = {'project': 'HISJB Evidence Chain', 'educational': True, 'synthetic_only': True,
                'node_id': settings.node_id, 'height': chain[-1].index, 'block_count': len(chain),
                'confirmed_transactions': sum(len(b.transactions) for b in chain), 'pending_transactions': len(pending),
                'pending': [t.to_dict() for t in pending], 'chain_valid': validation.valid,
                'cumulative_work': validation.cumulative_work, 'next_difficulty': next_difficulty(chain, state.config),
                'difficulty_config': {'initial': state.config.initial_difficulty, 'min': state.config.min_difficulty,
                                      'max': state.config.max_difficulty, 'retarget_window': state.config.retarget_window},
                'mining_busy': state.miner_lock.locked(), 'worker_model': 'one bounded mining thread per node',
                'last_mining': last_mining, 'last_block': chain[-1].to_dict(),
                'recent_blocks': [b.to_dict() for b in reversed(chain[-20:])],
                'sync': state.sync_status, 'peers_configured': list(settings.peers), 'actors': settings.actors,
                'network_hash': state.config.fingerprint, 'sampled_at': datetime.now(timezone.utc).isoformat()}
        return JSONResponse(data, headers=headers)

    @app.get('/console/api/nodes', include_in_schema=False)
    async def nodes(request: Request):
        gate(request, True)
        code, own = await backend('GET', '/chain')
        rows = [{'url': origin, 'node_id': settings.node_id, 'reachable': code == 200,
                 'height': len(own['blocks'])-1, 'tip': own['tip'], 'work': own['cumulative_work']}]
        async with httpx.AsyncClient(timeout=1, follow_redirects=False, trust_env=False) as client:
            for peer in settings.peers:
                try:
                    async with client.stream('GET', peer+'/chain', headers={'Authorization': 'Bearer '+credentials['peer']}) as response:
                        response.raise_for_status()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 4*1024*1024:
                                raise ValueError('response limit')
                        chain = json.loads(raw)
                    checked_chain = parse_chain(chain['blocks'], app.state.node.config)
                    validation = validate_chain(checked_chain, app.state.node.config)
                    rows.append({'url': peer, 'node_id': chain['node_id'], 'reachable': True,
                                 'height': checked_chain[-1].index, 'tip': checked_chain[-1].hash,
                                 'work': validation.cumulative_work})
                except (httpx.HTTPError, ValueError, TypeError, KeyError):
                    rows.append({'url': peer, 'reachable': False, 'error': 'peer unavailable or invalid response'})
        return JSONResponse({'nodes': rows, 'same_tip': all(r.get('tip') == rows[0]['tip'] for r in rows)}, headers=headers)

    @app.get('/console/api/fixture/{number}', include_in_schema=False)
    def fixture(number: int, request: Request):
        gate(request, True)
        return JSONResponse({'fixture_id': number, 'synthetic_content': fixture_bytes(number).decode(),
                             'document_hash': fixture_hash(number)}, headers=headers)

    @app.get('/console/api/block/{number}', include_in_schema=False)
    async def block(number: int, request: Request):
        gate(request, True)
        code, data = await backend('GET', f'/blocks/{number}')
        return JSONResponse(data, status_code=code, headers=headers)

    @app.get('/console/api/history/{document_id}', include_in_schema=False)
    async def history(document_id: str, request: Request):
        gate(request, True)
        # Reject arbitrary path construction before calling the internal API.
        from blockchain.transaction import is_uuid
        if not is_uuid(document_id):
            raise HTTPException(422, 'canonical UUIDv4 required')
        code, data = await backend('GET', f'/documents/{document_id}/history')
        return JSONResponse(data, status_code=code, headers=headers)

    @app.post('/console/api/command', include_in_schema=False)
    async def command(body: Command, request: Request):
        nonlocal last_mining
        gate(request, True)
        method, path, payload = 'POST', routes.get(body.action), body.payload
        if body.action in ('qr_read', 'qr_revoke'):
            from documents.qr import digest_token
            try:
                digest_token(payload.get('token'))
            except ValueError:
                raise HTTPException(422, 'invalid token') from None
            path = '/qr/' + payload['token'] + ('/revoke' if body.action == 'qr_revoke' else '')
            method = 'POST' if body.action == 'qr_revoke' else 'GET'
            payload = None
        started = time.perf_counter()
        code, data = await backend(method, path, body.role, payload)
        if body.action == 'mine' and code == 200:
            last_mining = {'height': data['block']['index'], 'hash': data['block']['hash'],
                'nonce': data['block']['nonce'], 'difficulty': data['block']['difficulty'],
                'attempts': data['attempts'], 'elapsed_seconds': data['elapsed_seconds'],
                'request_elapsed_seconds': time.perf_counter()-started,
                'measured_at': datetime.now(timezone.utc).isoformat()}
        return Response(status_code=204, headers=headers) if code == 204 else JSONResponse(data, status_code=code, headers=headers)
