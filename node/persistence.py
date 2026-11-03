"""Versioned atomic chain+mempool snapshots, checksum and exclusive directory writer."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from blockchain.block import Block
from blockchain.config import canonical_json
from blockchain.genesis import genesis
from blockchain.transaction import Transaction, validate_transaction
from blockchain.validation import validate_chain

MAX_STATE_BYTES = 4 * 1024 * 1024

class StateError(RuntimeError):
    pass

def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate JSON key')
        obj[key] = value
    return obj

def parse_chain(data, config):
    if type(data) is not list or not 1 <= len(data) <= config.max_chain_blocks:
        raise ValueError('invalid chain length')
    chain = tuple(Block.from_dict(b, max_transactions=config.max_transactions_per_block) for b in data)
    validation = validate_chain(chain, config)
    if not validation.valid:
        raise ValueError(validation.reason)
    return chain

class SnapshotStore:
    def __init__(self, directory: Path, node_id, config, max_pending):
        self.directory, self.node_id, self.config = Path(directory), node_id, config
        self.max_pending = max_pending
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'state.json'
        self.lock = (self.directory / '.writer.lock').open('a+b')
        try:
            self.lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                if self.lock.read(1) == b'':
                    self.lock.write(b'0'); self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.lock.close()
            raise StateError('data directory already has a writer') from exc

    def close(self):
        if not self.lock.closed:
            self.lock.close()

    def validate(self, chain, pending):
        result = validate_chain(chain, self.config)
        if not result.valid:
            raise StateError(result.reason)
        if type(pending) is not tuple or len(pending) > self.max_pending:
            raise StateError('invalid pending collection')
        seen = {t.tx_id for b in chain for t in b.transactions}
        for tx in pending:
            validate_transaction(tx, self.config.fingerprint)
            if tx.tx_id in seen or tx.timestamp < self.config.genesis_timestamp:
                raise StateError('replay or invalid pending timestamp')
            seen.add(tx.tx_id)

    def load(self):
        if not self.path.exists():
            chain, pending = (genesis(self.config),), ()
            self.save(chain, pending)
            return chain, pending
        try:
            with self.path.open('rb') as f:
                raw = f.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError('snapshot too large')
            envelope = json.loads(raw, object_pairs_hook=unique_object)
            if set(envelope) != {'payload','sha256'}:
                raise ValueError('invalid envelope')
            payload = envelope['payload']
            if hashlib.sha256(canonical_json(payload)).hexdigest() != envelope['sha256']:
                raise ValueError('checksum mismatch')
            if set(payload) != {'schema','node_id','network_hash','chain','pending'}:
                raise ValueError('invalid snapshot fields')
            if type(payload['schema']) is not int or payload['schema'] != 1:
                raise ValueError('unsupported schema')
            if payload['node_id'] != self.node_id or payload['network_hash'] != self.config.fingerprint:
                raise ValueError('node/network identity mismatch')
            chain = parse_chain(payload['chain'], self.config)
            if type(payload['pending']) is not list or len(payload['pending']) > self.max_pending:
                raise ValueError('invalid pending collection')
            pending = tuple(Transaction.from_dict(t) for t in payload['pending'])
            self.validate(chain, pending)
            return chain, pending
        except (OSError, ValueError, TypeError, KeyError, RecursionError, StateError) as exc:
            raise StateError('corrupt/incompatible snapshot; original preserved') from exc

    def save(self, chain, pending):
        try:
            self.validate(chain, pending)
            payload = {'schema':1, 'node_id':self.node_id, 'network_hash':self.config.fingerprint,
                       'chain':[b.to_dict() for b in chain], 'pending':[t.to_dict() for t in pending]}
            envelope = {'payload':payload, 'sha256':hashlib.sha256(canonical_json(payload)).hexdigest()}
            raw = canonical_json(envelope)
            if len(raw) > MAX_STATE_BYTES:
                raise StateError('snapshot size limit')
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.directory, prefix='.state-', suffix='.tmp', delete=False) as f:
                    temporary = Path(f.name)
                    f.write(raw); f.flush(); os.fsync(f.fileno())
                os.replace(temporary, self.path)
                if os.name != 'nt':
                    fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            finally:
                if temporary is not None and temporary.exists():
                    temporary.unlink()  # only the temporary file created by this save
        except (OSError, ValueError, TypeError) as exc:
            raise StateError('snapshot write failed; caller must fail closed') from exc
