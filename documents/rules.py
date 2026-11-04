"""Deterministic projection and admission rules on top of the original protocol."""
from functools import lru_cache
import hashlib
from blockchain.config import canonical_json
from blockchain.transaction import is_uuid, validate_transaction
from blockchain.validation import validate_chain

STAGES = ('NOTE_RECEIVED', 'DIRECTION_REVIEWED', 'LEGAL_REVIEWED',
          'VERSION_PREPARED', 'QR_IDENTIFIER_ISSUED', 'DELIVERY_RECORDED')
ROLES = ('mesa', 'direccion', 'legal', 'bio', 'bio', 'bio')
SCHEMA = 'synthetic-circuit-v1'


class DocumentConflict(ValueError):
    """No user-provided values in the error message."""


def fixture_bytes(number):
    if type(number) is not int or not 1 <= number <= 10000:
        raise ValueError('fixture must be 1..10000')
    return f'UNLU-SYNTHETIC-FIXTURE-{number:05}'.encode('ascii')


def fixture_hash(number):
    return hashlib.sha256(fixture_bytes(number)).hexdigest()


@lru_cache(maxsize=1)
def fixture_hashes():
    return frozenset(fixture_hash(n) for n in range(1, 10001))


def policy_network(actors):
    if set(actors) != {'mesa', 'direccion', 'legal', 'bio'}:
        raise ValueError('four configured synthetic actors required')
    if not all(is_uuid(v) for v in actors.values()) or len(set(actors.values())) != 4:
        raise ValueError('actors must be distinct canonical UUIDv4')
    return hashlib.sha256(canonical_json({'schema': SCHEMA, 'actors': actors})).hexdigest()


def validate_next(tx, records, actors, config):
    validate_transaction(tx, config.fingerprint)
    if tx.document_hash not in fixture_hashes():
        raise DocumentConflict('only controlled synthetic fixture hashes are accepted')
    stage = STAGES.index(tx.event_type)
    if tx.actor_id != actors[ROLES[stage]]:
        raise DocumentConflict('actor is not permitted for this event')
    history = records.get(tx.document_id, [])
    previous = history[-1] if history else None
    if previous and tx.timestamp <= previous.timestamp:
        raise DocumentConflict('document timestamp must increase')
    if stage == 0:
        if any(t.version_id == tx.version_id for t in history):
            raise DocumentConflict('version already exists')
        if previous:
            if previous.event_type != STAGES[-1]:
                raise DocumentConflict('previous version has not completed delivery')
            if (tx.previous_version_id, tx.previous_document_hash) != (previous.version_id, previous.document_hash):
                raise DocumentConflict('version must reference the last delivered version')
        elif tx.previous_version_id is not None:
            raise DocumentConflict('first version cannot reference another version')
    else:
        if previous is None or previous.version_id != tx.version_id:
            raise DocumentConflict('version is not the current version')
        if STAGES.index(previous.event_type) + 1 != stage:
            raise DocumentConflict('event is out of sequence')
        fields = ('document_hash', 'previous_version_id', 'previous_document_hash')
        if any(getattr(previous, field) != getattr(tx, field) for field in fields):
            raise DocumentConflict('version content or parent reference conflicts')


def project(chain, actors, config):
    checked = validate_chain(chain, config)
    if not checked.valid:
        raise DocumentConflict('invalid blockchain')
    if config.network_id != policy_network(actors):
        raise DocumentConflict('document policy and network identity differ')
    records = {}
    for block in chain:
        seen = set()
        for tx in block.transactions:
            # The predecessor must be in a previous committed block.
            if tx.document_id in seen:
                raise DocumentConflict('two stages for one document in one block')
            validate_next(tx, records, actors, config)
            records.setdefault(tx.document_id, []).append(tx)
            seen.add(tx.document_id)
    return records


def validate_pending(pending, records, actors, config):
    seen = set()
    for tx in pending:
        if tx.document_id in seen:
            raise DocumentConflict('one pending event per document is permitted')
        validate_next(tx, records, actors, config)
        seen.add(tx.document_id)


def public_transaction(tx):
    data = tx.to_dict()
    data['transaction_id'] = data.pop('tx_id')
    data['previous_version_hash'] = data.pop('previous_document_hash')
    # Closed, reproducible projection. No new fields added to consensus serialization.
    data['metadata'] = {'schema': SCHEMA, 'synthetic': True, 'role': ROLES[STAGES.index(tx.event_type)]}
    return data
