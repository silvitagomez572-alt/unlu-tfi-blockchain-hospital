"""Factory per node. All bindings are loopback-only in the phase-2 launcher."""
import asyncio
from contextlib import asynccontextmanager
import os
import time
from fastapi import FastAPI, HTTPException, Request, Path as ApiPath, Header
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse, Response
from prometheus_client import CollectorRegistry, Gauge, Histogram, Counter, generate_latest, CONTENT_TYPE_LATEST
from blockchain.block import Block
from blockchain.document_integrity import synthetic_document_hash, verify_document_hash
from blockchain.mining import MiningBudgetExceeded
from blockchain.transaction import Transaction
from blockchain.validation import validate_chain
from .state import NodeState, NodeError
from .p2p import PeerManager
from .schemas import TxRequest, BlockRequest, VerifyRequest, SyntheticRegister, UUID

class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ('POST','PUT','PATCH'):
            return await self.app(scope,receive,send)
        data = bytearray()
        deadline = time.monotonic()+3
        try:
            while True:
                message = await asyncio.wait_for(receive(),max(0.001,deadline-time.monotonic()))
                if message['type'] == 'http.disconnect':
                    return
                data.extend(message.get('body',b''))
                if len(data)>65536:
                    response = JSONResponse({'detail':'body exceeds 64 KiB'},status_code=413,headers={'Connection':'close'})
                    return await response(scope,receive,send)
                if not message.get('more_body',False):
                    break
                if time.monotonic()>=deadline:
                    raise TimeoutError
        except TimeoutError:
            return await JSONResponse({'detail':'request body timeout'},status_code=408)(scope,receive,send)
        emitted = False
        async def replay():
            nonlocal emitted
            if not emitted:
                emitted = True
                return {'type':'http.request','body':bytes(data),'more_body':False}
            return await receive()
        return await self.app(scope,replay,send)

def create_app(settings):
    registry = CollectorRegistry()
    metrics = {
        'height':Gauge('pow_block_height','Committed local height',registry=registry),
        'pending':Gauge('pow_mempool_transactions','Durably pending transactions',registry=registry),
        'peers':Gauge('pow_peers_connected','Peers reachable at latest synchronization',registry=registry),
        'mining':Histogram('pow_mining_duration_seconds','Successful mining time',registry=registry),
        'sync':Counter('pow_sync_total','Synchronization attempts',['result'],registry=registry),
        'forks':Counter('pow_chain_adoptions_total','Better chain adoptions including normal catch-up',registry=registry),
        'network_errors':Counter('pow_peer_events_total','Failed or rejected peer operations',['reason'],registry=registry),
        'errors':Counter('pow_validation_errors_total','Rejected requests',['reason'],registry=registry),
    }
    @asynccontextmanager
    async def lifespan(app):
        state = NodeState(settings)
        peers = PeerManager(state,metrics)
        app.state.node, app.state.peers = state, peers
        peers.start()
        try:
            yield
        finally:
            await peers.close()
            state.close()
    app = FastAPI(title='UNLu synthetic hospital node',version='0.2.0',lifespan=lifespan)
    app.add_middleware(BodyLimit)

    @app.exception_handler(NodeError)
    async def node_error(request, exc):
        metrics['errors'].labels(str(exc.status)).inc()
        return JSONResponse({'detail':exc.detail},status_code=exc.status)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        metrics['errors'].labels('invalid').inc()
        return JSONResponse({'detail':'invalid protocol data'},status_code=422)

    @app.exception_handler(RequestValidationError)
    async def schema_error(request, exc):
        metrics['errors'].labels('schema').inc()
        # Do not echo body values or personal data from rejected requests.
        return JSONResponse({'detail':'invalid request schema'},status_code=422)

    @app.exception_handler(MiningBudgetExceeded)
    async def mining_budget(request, exc):
        return JSONResponse({'detail':'mining budget exhausted; state unchanged'},status_code=503)

    @app.get('/healthz')
    def health():
        app.state.node.ensure_healthy()
        return {'status':'ok','node_id':settings.node_id,'pid':os.getpid()}

    @app.get('/readyz')
    def ready():
        app.state.node.ensure_healthy()
        result = app.state.node.sync_status
        return JSONResponse(result,status_code=200 if result['state'] in ('synced','isolated') else 503)

    @app.get('/metrics')
    def prometheus():
        chain,pending = app.state.node.snapshot()
        metrics['height'].set(chain[-1].index); metrics['pending'].set(len(pending))
        return Response(generate_latest(registry),media_type=CONTENT_TYPE_LATEST)

    @app.get('/chain')
    def chain():
        current,_ = app.state.node.snapshot()
        return {'node_id':settings.node_id,'network_hash':app.state.node.config.fingerprint,
                'tip':current[-1].hash,'cumulative_work':validate_chain(current,app.state.node.config).cumulative_work,
                'blocks':[b.to_dict() for b in current]}

    @app.get('/blocks/{index}')
    def block(index:int=ApiPath(ge=0,le=100_000)):
        current,_ = app.state.node.snapshot()
        if index>=len(current):
            raise HTTPException(404,'block not found')
        return current[index].to_dict()

    @app.get('/transactions/pending')
    def pending():
        return [t.to_dict() for t in app.state.node.snapshot()[1]]

    @app.post('/transactions',status_code=202)
    async def transaction(body:TxRequest, x_tfi_hops:int=Header(default=3,ge=0,le=3)):
        tx = body.transaction()
        await asyncio.to_thread(app.state.node.add_transaction,tx)
        if x_tfi_hops:
            app.state.peers.enqueue('/transactions',tx.to_dict(),x_tfi_hops-1)
        return {'tx_id':tx.tx_id,'status':'pending'}

    @app.get('/peers')
    def peers():
        return {'node_id':settings.node_id,'peers':app.state.peers.peers,'sync':app.state.node.sync_status}

    @app.post('/peers/sync')
    async def sync():
        return await app.state.peers.sync()

    @app.post('/mine')
    async def mine():
        result = await asyncio.to_thread(app.state.node.mine)
        metrics['mining'].observe(result.elapsed_seconds)
        app.state.peers.enqueue('/peers/blocks',result.block.to_dict())
        return {'block':result.block.to_dict(),'elapsed_seconds':result.elapsed_seconds,'attempts':result.attempts}

    @app.post('/peers/blocks')
    async def receive_block(body:BlockRequest, x_tfi_hops:int=Header(default=2,ge=0,le=3)):
        candidate = Block.from_dict(body.model_dump(),max_transactions=app.state.node.config.max_transactions_per_block)
        adopted = await asyncio.to_thread(app.state.node.accept_block,candidate)
        if adopted and x_tfi_hops:
            app.state.peers.enqueue('/peers/blocks',candidate.to_dict(),x_tfi_hops-1)
        return {'adopted':adopted}

    @app.post('/documents/register',status_code=202)
    async def register(body:SyntheticRegister):
        # Controlled fixture, never arbitrary document uploads.
        tx = Transaction.create(network_hash=app.state.node.config.fingerprint,
                document_id=body.document_id,version_id=body.version_id,actor_id=body.actor_id,
                document_hash=synthetic_document_hash(f'UNLU-SYNTHETIC-FIXTURE-{body.fixture_id:05}'.encode()),
                event_type='VERSION_PREPARED',timestamp=int(time.time()*1000))
        await asyncio.to_thread(app.state.node.register_transaction,tx)
        app.state.peers.enqueue('/transactions',tx.to_dict())
        return {'tx_id':tx.tx_id,'document_hash':tx.document_hash,'status':'pending','synthetic':True}

    @app.post('/documents/verify')
    def verify(body:VerifyRequest):
        return verify_document_hash(app.state.node.snapshot()[0],app.state.node.config,
                                    body.document_id,body.version_id,body.document_hash)

    @app.get('/documents/{document_id}/history')
    def history(document_id:str=ApiPath(pattern=UUID)):
        rows = [{'block':b.index,'block_hash':b.hash,**t.to_dict()} for b in app.state.node.snapshot()[0]
                for t in b.transactions if t.document_id==document_id]
        if not rows:
            raise HTTPException(404,'document not registered')
        return rows
    return app
