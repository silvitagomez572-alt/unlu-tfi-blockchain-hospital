import time
from uuid import UUID
import pytest
from blockchain.chain import mine_next
from blockchain.genesis import genesis
from blockchain.transaction import Transaction
from blockchain.validation import validate_chain
from blockchain.document_integrity import verify_document_hash
from documents.rules import STAGES, ROLES, fixture_hash, policy_network, project, public_transaction, DocumentConflict
from documents.state import DocumentSettings, DocumentState
from node.state import NodeError


def uid(n):
    return str(UUID(int=n, version=4))


ACTORS = {role: uid(900+i) for i, role in enumerate(('mesa', 'direccion', 'legal', 'bio'))}


def options(path):
    return DocumentSettings(node_id='document-test', data_dir=str(path), port=19901, actors=ACTORS,
        network={'network_id': policy_network(ACTORS), 'initial_difficulty': 1, 'max_difficulty': 1})


def entry(state, stage=0, version=101, fixture=1, previous=None, **overrides):
    history = [t for b in state.chain for t in b.transactions if t.document_id == uid(1)]
    fields = dict(network_hash=state.config.fingerprint, document_id=uid(1), version_id=uid(version),
        document_hash=fixture_hash(fixture), event_type=STAGES[stage], actor_id=ACTORS[ROLES[stage]],
        timestamp=max(int(time.time()*1000)-100, history[-1].timestamp+1 if history else 0),
        previous_version_id=uid(previous[0]) if previous else None,
        previous_document_hash=fixture_hash(previous[1]) if previous else None)
    return Transaction.create(**(fields | overrides))


def confirmed(state, stage, **kw):
    tx = entry(state, stage, **kw)
    state.add_transaction(tx)
    state.mine()
    return tx


def test_two_versions_complete_history_integrity_and_restart(tmp_path):
    state = DocumentState(options(tmp_path))
    try:
        for stage in range(6):
            confirmed(state, stage)
        for stage in range(6):
            confirmed(state, stage, version=102, fixture=2, previous=(101, 1))
        before = state.snapshot()
        rows = project(state.chain, ACTORS, state.config)[uid(1)]
        assert len(rows) == 12 and len({t.version_id for t in rows}) == 2
        assert rows[6].previous_document_hash == fixture_hash(1)
        for version, fixture in ((101, 1), (102, 2)):
            assert verify_document_hash(state.chain, state.config, uid(1), uid(version), fixture_hash(fixture))['integrity'] == 'MATCH'
        assert verify_document_hash(state.chain, state.config, uid(1), uid(102), 'f'*64)['integrity'] == 'MISMATCH'
        assert verify_document_hash(state.chain, state.config, uid(1), uid(103), fixture_hash(1))['integrity'] == 'NOT_FOUND'
        dto = public_transaction(rows[6])
        assert dto['transaction_id'] == rows[6].tx_id and dto['previous_version_hash'] == fixture_hash(1)
        assert dto['metadata'] == {'schema': 'synthetic-circuit-v1', 'synthetic': True, 'role': 'mesa'}
    finally:
        state.close()
    recovered = DocumentState(options(tmp_path))
    try:
        assert recovered.snapshot() == before
    finally:
        recovered.close()


@pytest.mark.parametrize('case', ['out_of_order', 'actor', 'hash', 'duplicate', 'parent', 'pending', 'timestamp'])
def test_document_rejections_preserve_state(tmp_path, case):
    state = DocumentState(options(tmp_path))
    try:
        first = confirmed(state, 0)
        cases = {
            'out_of_order': entry(state, 2),
            'actor': entry(state, 1, actor_id=ACTORS['bio']),
            'hash': entry(state, 1, fixture=2),
            'duplicate': first,
            'parent': entry(state, 0, version=102, fixture=2, previous=(101, 1)),
            'pending': entry(state, 1),
            'timestamp': entry(state, 1, timestamp=first.timestamp),
        }
        if case == 'pending':
            state.add_transaction(cases[case])
        before, disk = state.snapshot(), state.store.path.read_bytes()
        with pytest.raises(NodeError):
            state.add_transaction(cases[case])
        assert state.snapshot() == before and state.store.path.read_bytes() == disk
    finally:
        state.close()


def test_invalid_document_chain_is_not_adopted_or_loaded(tmp_path):
    state = DocumentState(options(tmp_path))
    bad_tx = entry(state, 3)
    invalid = state.chain + (mine_next(state.chain, (bad_tx,), bad_tx.timestamp, state.config).block,)
    assert validate_chain(invalid, state.config).valid  # PoW validity alone is insufficient.
    before = state.snapshot()
    try:
        with pytest.raises(NodeError, match='documentary'):
            state.adopt(invalid)
        assert state.snapshot() == before
        state.store.save(invalid, ())  # Controlled disk-injection fixture only.
        preserved = state.store.path.read_bytes()
    finally:
        state.close()
    with pytest.raises(DocumentConflict):
        DocumentState(options(tmp_path))
    assert (tmp_path/'state.json').read_bytes() == preserved


def test_reorg_pending_readmission_preserves_confirmed_predecessor_rule(tmp_path):
    state = DocumentState(options(tmp_path))
    try:
        first = confirmed(state, 0)
        confirmed(state, 1)
        alternative = (genesis(state.config),)
        for i in range(3):
            alternative += (mine_next(alternative, (), int(time.time()*1000)-50+i, state.config).block,)
        assert state.adopt(alternative)
        assert state.chain == alternative and state.pending == (first,)
        state.mine()
        assert project(state.chain, ACTORS, state.config)[uid(1)] == [first]
    finally:
        state.close()


def test_wrong_parent_and_fixture_are_rejected(tmp_path):
    state = DocumentState(options(tmp_path))
    try:
        for stage in range(6):
            confirmed(state, stage)
        for bad in (entry(state, 0, version=102, previous=(101, 2)),
                    entry(state, 0, version=102, previous=(101, 1), document_hash='a'*64)):
            with pytest.raises(NodeError):
                state.add_transaction(bad)
        assert not state.pending
    finally:
        state.close()
