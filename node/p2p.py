"""Bounded loopback-only peer transport with anti-entropy and deduplicated flooding."""
import asyncio
import json
import logging
import time
import httpx
from blockchain.transaction import Transaction
from .persistence import parse_chain, unique_object, MAX_STATE_BYTES
from .state import NodeError

LOG = logging.getLogger('tfi.peer')

class PeerManager:
    def __init__(self, state, metrics):
        self.state, self.metrics = state, metrics
        self.peers = [p for p in state.settings.peers if p != f'http://127.0.0.1:{state.settings.port}']
        self.queue = asyncio.Queue(maxsize=128)
        self.sync_lock = asyncio.Lock()
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(1.0, connect=0.5),
                                       limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
                                       follow_redirects=False, trust_env=False)
        self.tasks = []

    async def request(self, peer, method, path, payload=None, hops=0):
        if peer not in self.peers:
            raise ValueError('peer not allowlisted')
        async def bounded():
            async with self.client.stream(method, peer+path, json=payload,
                                          headers={'X-TFI-Hops':str(hops)}) as response:
                if response.status_code >= 300:
                    raise httpx.HTTPStatusError('peer rejected request', request=response.request, response=response)
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_STATE_BYTES:
                        raise ValueError('peer response exceeds byte limit')
                return json.loads(raw, object_pairs_hook=unique_object)
        return await asyncio.wait_for(bounded(), 2)

    def enqueue(self, path, payload, hops=2):
        if hops < 0:
            return
        try:
            self.queue.put_nowait((path,payload,hops))
        except asyncio.QueueFull:
            self.metrics['network_errors'].labels('queue_full').inc()
            LOG.warning('outbox full; periodic anti-entropy will recover')

    async def sync(self):
        if self.sync_lock.locked():
            raise NodeError(409, 'synchronization busy')
        async with self.sync_lock:
            errors, healthy, adopted = [], 0, False
            self.state.sync_status = {'state':'syncing','last_success_ms':self.state.sync_status.get('last_success_ms'),
                                      'errors':[], 'adopted':False}
            deadline = time.monotonic()+6
            for peer in self.peers:
                try:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('overall sync deadline')
                    data = await asyncio.wait_for(self.request(peer,'GET','/chain'), remaining)
                    if not isinstance(data,dict) or data.get('network_hash') != self.state.config.fingerprint:
                        raise ValueError('peer network mismatch')
                    candidate = parse_chain(data['blocks'], self.state.config)
                    changed = await asyncio.to_thread(self.state.adopt, candidate)
                    adopted |= changed
                    healthy += 1
                    if changed:
                        self.metrics['forks'].inc()
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('overall sync deadline')
                    pending = await asyncio.wait_for(self.request(peer,'GET','/transactions/pending'), remaining)
                    if not isinstance(pending, list) or len(pending)>self.state.settings.max_pending:
                        raise ValueError('invalid peer mempool')
                    for raw in pending:
                        tx = Transaction.from_dict(raw)
                        try:
                            await asyncio.to_thread(self.state.add_transaction, tx)
                        except NodeError as exc:
                            if exc.status != 409:
                                raise
                except (httpx.HTTPError, ValueError, TypeError, KeyError, TimeoutError, NodeError) as exc:
                    errors.append({'peer':peer, 'error':type(exc).__name__})
                    self.metrics['network_errors'].labels('sync').inc()
                    LOG.info('sync peer=%s result=%s',peer,type(exc).__name__)
            ok = not errors
            result = {'state':'isolated' if not self.peers else 'synced' if ok else 'degraded',
                      'last_success_ms':int(time.time()*1000) if ok else self.state.sync_status.get('last_success_ms'),
                      'errors':errors,'adopted':adopted, 'reachable_peers':healthy}
            self.state.sync_status = result
            self.metrics['peers'].set(healthy)
            self.metrics['sync'].labels('success' if ok else 'partial').inc()
            LOG.info('sync node=%s state=%s adopted=%s peers=%s',self.state.settings.node_id,result['state'],adopted,healthy)
            return result

    async def worker(self):
        while True:
            path, payload, hops = await self.queue.get()
            try:
                for peer in self.peers:
                    try:
                        await self.request(peer,'POST',path,payload,hops)
                    except (httpx.HTTPError, ValueError, TimeoutError):
                        # Duplicates return 409. Network failures are recovered by sync.
                        self.metrics['network_errors'].labels('delivery').inc()
            finally:
                self.queue.task_done()

    async def periodic(self):
        while True:
            try:
                await self.sync()
            except NodeError:
                pass
            await asyncio.sleep(self.state.settings.sync_interval_seconds)

    def start(self):
        self.tasks = [asyncio.create_task(self.worker()), asyncio.create_task(self.periodic())]

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.aclose()
