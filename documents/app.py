"""Document profile. Never receives document bytes or free-text clinical metadata."""
import asyncio
import io
import sqlite3
import time
from typing import Literal
from fastapi import HTTPException, Request, Path as ApiPath
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse
from blockchain.document_integrity import verify_document_hash
from blockchain.transaction import Transaction
from node.app import create_app
from node.p2p import PeerManager
from node.schemas import UUID, HEX as HASH, VerifyRequest
from .state import DocumentState
from .rules import STAGES, ROLES, SCHEMA, fixture_hash, project, public_transaction
from .qr import QRStore, AccessDenied
from .security import AccessControl, validate_credentials


class Metadata(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, populate_by_name=True)
    profile_schema: Literal['synthetic-circuit-v1'] = Field(default=SCHEMA, alias='schema')
    synthetic: Literal[True] = True


class Register(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    document_id: str = Field(pattern=UUID)
    version_id: str = Field(pattern=UUID)
    fixture_id: int = Field(ge=1, le=10000)
    metadata: Metadata = Field(default_factory=Metadata)


class Version(Register):
    previous_version_id: str = Field(pattern=UUID)
    previous_version_hash: str = Field(pattern=HASH)


class Event(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    document_id: str = Field(pattern=UUID)
    version_id: str = Field(pattern=UUID)
    event_type: Literal['DIRECTION_REVIEWED', 'LEGAL_REVIEWED', 'VERSION_PREPARED', 'DELIVERY_RECORDED']


class QRCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    document_id: str = Field(pattern=UUID)
    version_id: str = Field(pattern=UUID)
    ttl_seconds: int = Field(default=300, ge=60, le=3600)
    max_uses: int = Field(default=1, ge=1, le=10)


def create_document_app(settings, credentials, *, qr_clock=time.time, rate_clock=time.monotonic, rate_limit=120):
    validate_credentials(credentials)

    def state_factory(opts):
        state = DocumentState(opts)
        try:
            state.qr = QRStore(opts.directory() / 'qr.sqlite3', clock=qr_clock)
        except BaseException:
            state.close()
            raise
        return state

    def peer_factory(state, metrics):
        peers = PeerManager(state, metrics)
        peers.client.headers['Authorization'] = 'Bearer ' + credentials['peer']
        return peers

    app = create_app(settings, state_factory=state_factory, peer_factory=peer_factory)
    app.title = 'UNLu synthetic documentary profile'
    app.version = '0.3.0'
    app.router.routes = [r for r in app.router.routes if not getattr(r, 'path', '').startswith('/documents/')]
    app.add_middleware(AccessControl, credentials=credentials, clock=rate_clock, limit=rate_limit, console=settings.console)

    @app.exception_handler(sqlite3.DatabaseError)
    async def unavailable(request, exc):
        return JSONResponse({'detail': 'grant storage unavailable'}, status_code=503)

    def require(request, role):
        if request.state.document_role != role:
            raise HTTPException(403, 'role cannot perform this administrative event')

    def current(state, document_id, version_id=None):
        records = project(state.chain, settings.actors, state.config)
        rows = records.get(document_id, [])
        if not rows:
            raise HTTPException(404, 'document not found')
        last = rows[-1]
        if version_id is not None and last.version_id != version_id:
            raise HTTPException(409, 'version is not current')
        return last

    def make_event(state, last, event_type):
        return Transaction.create(**(last.payload() | {
            'event_type': event_type, 'actor_id': settings.actors[ROLES[STAGES.index(event_type)]],
            'timestamp': max(int(time.time() * 1000), last.timestamp + 1)}))

    def registered(body, is_version):
        state = app.state.node
        with state.lock:
            state.ensure_healthy()
            records = project(state.chain, settings.actors, state.config)
            last = records.get(body.document_id, [])
            if not is_version and last:
                raise HTTPException(409, 'document exists; use versions')
            if is_version and not last:
                raise HTTPException(404, 'parent document not found')
            tx = Transaction.create(network_hash=state.config.fingerprint,
                document_id=body.document_id, version_id=body.version_id,
                document_hash=fixture_hash(body.fixture_id), event_type='NOTE_RECEIVED',
                actor_id=settings.actors['mesa'], timestamp=max(int(time.time()*1000), last[-1].timestamp+1 if last else 0),
                previous_version_id=body.previous_version_id if is_version else None,
                previous_document_hash=body.previous_version_hash if is_version else None)
            state.add_transaction(tx)
        return tx

    def queued(tx):
        app.state.peers.enqueue('/transactions', tx.to_dict())
        return {**public_transaction(tx), 'status': 'pending'}

    @app.post('/documents/register', status_code=202)
    async def register(body: Register, request: Request):
        require(request, 'mesa')
        return queued(await asyncio.to_thread(registered, body, False))

    @app.post('/documents/versions', status_code=202)
    async def version(body: Version, request: Request):
        require(request, 'mesa')
        return queued(await asyncio.to_thread(registered, body, True))

    @app.post('/documents/events', status_code=202)
    async def event(body: Event, request: Request):
        require(request, ROLES[STAGES.index(body.event_type)])
        def submit():
            state = app.state.node
            with state.lock:
                state.ensure_healthy()
                tx = make_event(state, current(state, body.document_id, body.version_id), body.event_type)
                state.add_transaction(tx)
                return tx
        return queued(await asyncio.to_thread(submit))

    def verified(state, document_id, version_id, document_hash):
        project(state.chain, settings.actors, state.config)
        result = verify_document_hash(state.chain, state.config, document_id, version_id, document_hash)
        return {**result, 'hash_presented': document_hash, 'hash_calculated': None,
                'hash_registered': sorted({r['document_hash'] for r in result['registrations']}),
                'hash_method': 'client-supplied SHA-256; no document upload',
                'height': state.chain[-1].index}

    @app.post('/documents/verify')
    def verify(body: VerifyRequest):
        state = app.state.node
        with state.lock:
            state.ensure_healthy()
            return verified(state, body.document_id, body.version_id, body.document_hash)

    @app.get('/documents/{document_id}/history')
    def history(document_id: str = ApiPath(pattern=UUID)):
        state = app.state.node
        with state.lock:
            state.ensure_healthy()
            current(state, document_id)
            return [{'block': b.index, 'block_hash': b.hash, **public_transaction(t)}
                    for b in state.chain for t in b.transactions if t.document_id == document_id]

    @app.post('/qr/create', status_code=202)
    async def create_qr(body: QRCreate):
        def create():
            import qrcode
            from qrcode.image.svg import SvgPathImage
            state = app.state.node
            with state.lock:
                state.ensure_healthy()
                last = current(state, body.document_id, body.version_id)
                if last.event_type != 'VERSION_PREPARED' or any(t.document_id == body.document_id for t in state.pending):
                    raise HTTPException(409, 'QR requires confirmed preparation and no pending event')
                tx = make_event(state, last, 'QR_IDENTIFIER_ISSUED')
                grant = state.qr.issue(tx.document_id, tx.version_id, tx.document_hash, tx.tx_id,
                                       body.ttl_seconds, body.max_uses)
                try:
                    url = f'http://127.0.0.1:{settings.port}/qr/' + grant['token']
                    image = qrcode.make(url, image_factory=SvgPathImage)
                    buffer = io.BytesIO()
                    image.save(buffer)
                    state.add_transaction(tx)
                except BaseException:
                    state.qr.revoke(grant['token'])
                    raise
                return tx, {**grant, 'url': url, 'qr_svg': buffer.getvalue().decode(),
                            'transaction_id': tx.tx_id, 'status': 'pending_confirmation',
                            'access_requires': 'token and an authenticated non-peer role'}
        tx, grant = await asyncio.to_thread(create)
        app.state.peers.enqueue('/transactions', tx.to_dict())
        return grant

    @app.get('/qr/{token}')
    def resolve_qr(token: str):
        state = app.state.node
        try:
            with state.lock:
                state.ensure_healthy()
                def check(reference):
                    result = verified(state, reference['document_id'], reference['version_id'], reference['document_hash'])
                    issuance = any(t.tx_id == reference['transaction_id'] and t.event_type == 'QR_IDENTIFIER_ISSUED'
                                   for b in state.chain for t in b.transactions)
                    if result['integrity'] != 'MATCH' or not issuance:
                        raise AccessDenied('access unavailable')
                    return result
                return state.qr.resolve(token, check)
        except AccessDenied:
            raise HTTPException(403, 'access unavailable') from None

    @app.post('/qr/{token}/revoke', status_code=204)
    def revoke_qr(token: str):
        try:
            if not app.state.node.qr.revoke(token):
                raise AccessDenied('access unavailable')
        except AccessDenied:
            raise HTTPException(403, 'access unavailable') from None

    if settings.console:
        from webconsole.server import install_console
        install_console(app, settings, credentials)
    return app
