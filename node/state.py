import threading
import time
import json
import logging
from blockchain.chain import mine_next
from blockchain.consensus import choose_best_chain
from blockchain.transaction import validate_transaction
from blockchain.validation import validate_chain
from .persistence import SnapshotStore, StateError

FORK_LOG = logging.getLogger('tfi.forkchoice')

class NodeError(RuntimeError):
    def __init__(self, status, detail):
        self.status, self.detail = status, detail
        super().__init__(detail)

class NodeState:
    def __init__(self, settings):
        self.settings, self.config = settings, settings.config()
        self.lock = threading.RLock()
        self.miner_lock = threading.Lock()
        self.healthy = True
        self.closed = False
        self.store = SnapshotStore(settings.directory(), settings.node_id, self.config, settings.max_pending)
        try:
            self.chain, self.pending = self.store.load()
        except BaseException:
            self.store.close()
            raise
        self.sync_status = {'state':'starting', 'last_success_ms':None, 'errors':[], 'adopted':False}

    def ensure_healthy(self):
        if self.closed or not self.healthy:
            raise NodeError(503, 'persistent state unavailable; restart and inspect storage')

    def commit(self, chain, pending):
        self.ensure_healthy()
        try:
            self.store.save(chain, pending)
        except StateError as exc:
            self.healthy = False
            raise NodeError(503, 'persistent state write failed') from exc
        self.chain, self.pending = chain, pending

    def snapshot(self):
        with self.lock:
            self.ensure_healthy()
            return self.chain, self.pending

    def admit_time(self, timestamp):
        if timestamp > int(time.time()*1000)+30_000:
            raise NodeError(422, 'timestamp exceeds local clock tolerance')

    def add_transaction(self, tx):
        validate_transaction(tx, self.config.fingerprint)
        self.admit_time(tx.timestamp)
        if tx.timestamp < self.config.genesis_timestamp:
            raise NodeError(422, 'transaction predates genesis')
        with self.lock:
            self.ensure_healthy()
            seen = {t.tx_id for b in self.chain for t in b.transactions} | {t.tx_id for t in self.pending}
            if tx.tx_id in seen:
                raise NodeError(409, 'duplicate or already confirmed transaction')
            if len(self.pending) >= self.settings.max_pending:
                raise NodeError(429, 'mempool full')
            self.commit(self.chain, self.pending + (tx,))

    def register_transaction(self, tx):
        with self.lock:
            self.ensure_healthy()
            entries = [*(t for b in self.chain for t in b.transactions),*self.pending]
            if any((t.document_id,t.version_id)==(tx.document_id,tx.version_id) for t in entries):
                raise NodeError(409,'version already registered or pending')
            self.add_transaction(tx)

    def adopt(self, candidate):
        started = time.perf_counter()
        # Validate without the write lock, then compare against the current tip under lock.
        result = validate_chain(candidate, self.config)
        if not result.valid:
            raise NodeError(422, result.reason)
        self.admit_time(candidate[-1].timestamp)
        with self.lock:
            self.ensure_healthy()
            previous = self.chain
            previous_work = validate_chain(previous, self.config).cumulative_work
            best = choose_best_chain((self.chain, candidate), self.config)
            decision = {'node_id':self.settings.node_id, 'current_tip':previous[-1].hash,
                        'current_work':previous_work,'candidate_tip':candidate[-1].hash,
                        'candidate_work':result.cumulative_work, 'selected_tip':best[-1].hash,
                        'rule':'greater_work' if previous_work!=result.cumulative_work else 'lexicographic_tip',
                        'adopted':best!=previous}
            if best == self.chain:
                decision['elapsed_ms'] = (time.perf_counter()-started)*1000
                FORK_LOG.info('fork_choice %s',json.dumps(decision,sort_keys=True))
                return False
            confirmed = {t.tx_id for b in best for t in b.transactions}
            # Orphaned transactions return to the mempool; never silently truncate it.
            restored = {t.tx_id:t for t in self.pending}
            restored.update({t.tx_id:t for b in self.chain for t in b.transactions if t.tx_id not in confirmed})
            pending = tuple(t for key,t in sorted(restored.items()) if key not in confirmed)
            if len(pending) > self.settings.max_pending:
                raise NodeError(429, 'reorg would overflow mempool; operator must resolve capacity')
            self.commit(best, pending)
            decision['elapsed_ms'] = (time.perf_counter()-started)*1000
            FORK_LOG.info('fork_choice %s',json.dumps(decision,sort_keys=True))
            return True

    def accept_block(self, block):
        with self.lock:
            self.ensure_healthy()
            if any(b.hash == block.hash for b in self.chain):
                return False
            chain = self.chain
        if block.index != len(chain) or block.previous_hash != chain[-1].hash:
            raise NodeError(409, 'divergent tip; full peer synchronization required')
        return self.adopt(chain+(block,))

    def mine(self):
        if not self.miner_lock.acquire(blocking=False):
            raise NodeError(409, 'miner busy')
        try:
            chain, pending = self.snapshot()
            batch = pending[:self.config.max_transactions_per_block]
            timestamp = max(int(time.time()*1000), chain[-1].timestamp+1,
                            max((t.timestamp for t in batch), default=0))
            self.admit_time(timestamp)
            result = mine_next(chain, batch, timestamp, self.config, max_attempts=100_000, timeout_seconds=1)
            with self.lock:
                self.ensure_healthy()
                if self.chain[-1].hash != chain[-1].hash:
                    raise NodeError(409, 'tip changed during mining; result discarded')
                removed = {t.tx_id for t in batch}
                self.commit(chain+(result.block,), tuple(t for t in self.pending if t.tx_id not in removed))
            return result
        finally:
            self.miner_lock.release()

    def close(self):
        with self.lock:
            self.closed = True
            self.store.close()
