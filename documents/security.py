"""Local-only role gates; not an institutional identity or transaction signature."""
from collections import deque
import re
import secrets
import threading
import time
from starlette.responses import JSONResponse

KEY_ROLES = frozenset({'mesa', 'direccion', 'legal', 'bio', 'auditor', 'operator', 'peer'})


def validate_credentials(credentials):
    if set(credentials) != KEY_ROLES or len(set(credentials.values())) != len(KEY_ROLES):
        raise ValueError('seven distinct ephemeral role credentials required')
    if not all(isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]{32,128}', v) for v in credentials.values()):
        raise ValueError('credentials must be random ASCII tokens of 32..128 characters')


class AccessControl:
    def __init__(self, app, credentials, clock=time.monotonic, limit=120, console=False):
        validate_credentials(credentials)
        self.app, self.credentials, self.clock, self.limit = app, credentials, clock, limit
        self.windows = {role: deque() for role in KEY_ROLES | {'anonymous'}}
        self.lock = threading.Lock()
        self.console = console

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path, method = scope['path'], scope['method']
        if self.console and (path == '/console' or path.startswith('/console/')):
            # The console enforces its own local session, Host/Origin and CSRF gate.
            return await self.app(scope, receive, send)
        headers_out = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                       'X-Content-Type-Options': 'nosniff'}

        async def secured_send(message):
            if message['type'] == 'http.response.start':
                message = dict(message)
                message['headers'] = list(message.get('headers', [])) + [
                    (k.lower().encode(), v.encode()) for k, v in headers_out.items()]
            await send(message)

        if method == 'GET' and path in ('/healthz', '/readyz', '/metrics'):
            return await self.app(scope, receive, secured_send)
        supplied = dict(scope['headers']).get(b'authorization', b'')
        role = 'anonymous'
        if len(supplied) <= 140 and supplied.startswith(b'Bearer '):
            for name, value in self.credentials.items():
                if secrets.compare_digest(supplied[7:], value.encode('ascii')):
                    role = name
        now = self.clock()
        with self.lock:
            window = self.windows[role]
            while window and now - window[0] >= 60:
                window.popleft()
            maximum = 2400 if role == 'peer' else 30 if role == 'anonymous' else self.limit
            limited = len(window) >= maximum
            if not limited:
                window.append(now)
        if limited:
            return await JSONResponse({'detail': 'rate limit exceeded'}, status_code=429,
                                      headers={'Retry-After': '60'})(scope, receive, secured_send)
        if role == 'anonymous':
            return await JSONResponse({'detail': 'unauthorized'}, status_code=401)(scope, receive, secured_send)
        permitted = True
        if role == 'peer':
            permitted = (method == 'GET' and path in ('/chain', '/transactions/pending')) or (
                method == 'POST' and path in ('/transactions', '/peers/blocks'))
        elif method == 'POST' and path in ('/transactions', '/peers/blocks'):
            permitted = False
        elif method == 'POST' and path in ('/mine', '/peers/sync'):
            permitted = role == 'operator'
        elif method == 'POST' and path.startswith('/qr/'):
            permitted = role == 'bio'
        if not permitted:
            return await JSONResponse({'detail': 'forbidden'}, status_code=403)(scope, receive, secured_send)
        scope.setdefault('state', {})['document_role'] = role
        return await self.app(scope, receive, secured_send)
