"""Small deterministic cases; no servers, containers, cloud or multiprocessing."""
from dataclasses import FrozenInstanceError, replace
from uuid import UUID
import pytest
from blockchain.block import Block
from blockchain.chain import mine_next
from blockchain.config import NetworkConfig
from blockchain.consensus import choose_best_chain
from blockchain.difficulty import block_work, next_difficulty
from blockchain.document_integrity import synthetic_document_hash, verify_document_hash
from blockchain.genesis import genesis
from blockchain.mining import MiningBudgetExceeded, mine
from blockchain.transaction import Transaction
from blockchain.validation import validate_chain


def identifier(n):
    return str(UUID(int=n, version=4))


def config(**changes):
    return NetworkConfig(target_interval_ms=1000, retarget_window=2, **changes)


def transaction(cfg, **changes):
    fields = dict(network_hash=cfg.fingerprint, document_id=identifier(1),
                  version_id=identifier(2), actor_id=identifier(3),
                  document_hash=synthetic_document_hash(b"SYNTHETIC-FIXTURE-001"),
                  event_type="VERSION_PREPARED", timestamp=50)
    return Transaction.create(**(fields | changes))


def build(cfg, timestamps, transactions=()):
    chain = (genesis(cfg),)
    for index, timestamp in enumerate(timestamps):
        result = mine_next(chain, transactions if index == 0 else (), timestamp, cfg,
                           max_attempts=50_000, timeout_seconds=0.5)
        chain += (result.block,)
    return chain


def test_canonical_roundtrip_and_network_domain():
    cfg = config()
    chain = build(cfg, [100], (transaction(cfg),))
    payload = chain[-1].to_dict()
    payload = dict(reversed(list(payload.items())))
    assert Block.from_dict(payload) == chain[-1]
    assert validate_chain(chain, cfg).valid
    other = config(network_id="unlu-other-network")
    assert genesis(other) != genesis(cfg)
    assert not validate_chain(chain, other).valid


def test_difficulty_retargets_fast_slow_and_exact_boundaries():
    cfg = config()
    fast = build(cfg, [100, 200, 300])
    assert [b.difficulty for b in fast] == [1, 1, 1, 2]
    assert validate_chain(fast, cfg).valid
    higher = config(initial_difficulty=2)
    slow = build(higher, [3000, 6000, 9000])
    assert slow[-1].difficulty == 1
    assert next_difficulty(build(cfg, [4000, 8000]), cfg) == 1
    capped = config(max_difficulty=1)
    assert next_difficulty(build(capped, [10, 20]), capped) == 1
    # Both exact threshold equalities retain difficulty.
    assert next_difficulty(build(cfg, [500, 1000]), cfg) == 1
    assert next_difficulty(build(cfg, [2000, 4000]), cfg) == 1


def test_fork_choice_uses_verified_work_not_length():
    cfg = config()
    shorter = build(cfg, [100, 200, 300])
    longer = build(cfg, [3000, 6000, 9000, 12000, 15000])
    assert len(shorter) < len(longer)
    assert validate_chain(shorter, cfg).cumulative_work == 3 * 16 + 256
    assert choose_best_chain((longer, shorter), cfg) == shorter
    assert choose_best_chain((shorter, longer), cfg) == shorter


def test_tie_break_and_invalid_candidate_order():
    cfg = config()
    a, b = build(cfg, [100]), build(cfg, [110])
    expected = min((a, b), key=lambda c: c[-1].hash)
    invalid = a[:-1] + (replace(a[-1], hash="0" * 64),)
    assert choose_best_chain((a, b, invalid), cfg) == expected
    assert choose_best_chain((invalid, b, a), cfg) == expected
    assert choose_best_chain((invalid,), cfg) is None


@pytest.mark.parametrize("field,value", [
    ("index", True), ("index", 7), ("nonce", -1), ("nonce", True),
    ("timestamp", float("nan")), ("timestamp", 0), ("timestamp", True),
    ("difficulty", True), ("difficulty", 3), ("previous_hash", "f" * 64),
    ("hash", "f" * 64), ("network_hash", "f" * 64),
    ("transactions", []), ("transactions", ({"name": "not allowed"},)),
])
def test_mutated_block_is_rejected(field, value):
    cfg = config()
    chain = build(cfg, [100])
    bad = chain[:-1] + (replace(chain[-1], **{field: value}),)
    assert not validate_chain(bad, cfg).valid


def test_remined_wrong_difficulty_and_genesis_are_rejected():
    cfg = config()
    chain = build(cfg, [100])
    wrong = mine(replace(chain[-1], difficulty=2, nonce=0, hash="")).block
    result = validate_chain((chain[0], wrong), cfg)
    assert not result.valid and "difficulty" in result.reason
    fake = mine(replace(chain[0], timestamp=1, nonce=0, hash="")).block
    assert not validate_chain((fake,), cfg).valid


def test_hash_without_proof_is_rejected():
    cfg = config()
    chain = build(cfg, [100])
    block = chain[-1]
    nonce = next(n for n in range(100) if not block.compute_hash(n).startswith("0"))
    bad = replace(block, nonce=nonce, hash=block.compute_hash(nonce))
    result = validate_chain((chain[0], bad), cfg)
    assert not result.valid and "proof" in result.reason


@pytest.mark.parametrize("changes", [
    {"timestamp": True}, {"timestamp": -1}, {"timestamp": float("inf")},
    {"document_id": "patient-1"}, {"document_hash": "bad"},
    {"event_type": "FREE_TEXT"}, {"previous_version_id": identifier(9)},
    {"previous_version_id": identifier(2), "previous_document_hash": "a" * 64},
])
def test_transaction_schema_rejects_invalid_metadata(changes):
    with pytest.raises(ValueError):
        transaction(config(), **changes)


def test_unknown_fields_and_payload_tampering_are_rejected():
    tx = transaction(config())
    with pytest.raises(ValueError):
        Transaction.from_dict(tx.to_dict() | {"document": "not allowed"})
    with pytest.raises(ValueError):
        Transaction.from_dict(tx.to_dict() | {"document_hash": "f" * 64})


def test_exact_replay_rejected_inside_and_across_blocks():
    cfg = config()
    tx = transaction(cfg)
    base = (genesis(cfg),)
    with pytest.raises(ValueError, match="replayed"):
        mine_next(base, (tx, tx), 100, cfg)
    chain = build(cfg, [100], (tx,))
    with pytest.raises(ValueError, match="replayed"):
        mine_next(chain, (tx,), 200, cfg)
    forged = Block(2, chain[-1].hash, (tx,), 200, 1, cfg.fingerprint)
    result = validate_chain(chain + (mine(forged).block,), cfg)
    assert not result.valid and "replayed" in result.reason


def test_future_tx_and_cross_network_tx_rejected_before_mining():
    cfg = config()
    with pytest.raises(ValueError, match="timestamp"):
        mine_next((genesis(cfg),), (transaction(cfg, timestamp=101),), 100, cfg)
    with pytest.raises(ValueError, match="network"):
        mine_next((genesis(cfg),), (transaction(config(network_id="another")),), 100, cfg)


def test_mining_records_attempts_and_does_not_mutate_input():
    cfg = config()
    candidate = Block(1, genesis(cfg).hash, (), 100, 1, cfg.fingerprint)
    result = mine(candidate)
    assert result.attempts > 0 and result.elapsed_seconds >= 0
    assert result.block.hash.startswith("0") and candidate.hash == ""
    with pytest.raises(FrozenInstanceError):
        result.block.nonce = 5


def test_attempt_and_time_budgets_are_enforced(monkeypatch):
    cfg = config()
    candidate = Block(1, genesis(cfg).hash, (), 100, 6, cfg.fingerprint)
    nonce = next(n for n in range(100) if not candidate.compute_hash(n).startswith("000000"))
    candidate = replace(candidate, nonce=nonce)
    with pytest.raises(MiningBudgetExceeded):
        mine(candidate, max_attempts=1)
    times = iter((0.0, 2.0))
    monkeypatch.setattr("blockchain.mining.time.perf_counter", lambda: next(times))
    with pytest.raises(MiningBudgetExceeded):
        mine(candidate, timeout_seconds=1)
    assert candidate.hash == ""


def test_document_integrity_detects_changes_missing_and_conflicts():
    cfg = config()
    tx = transaction(cfg)
    chain = build(cfg, [100], (tx,))
    def verify(c, h):
        return verify_document_hash(c, cfg, tx.document_id, tx.version_id, h)
    receipt = verify(chain, tx.document_hash)
    assert receipt["integrity"] == "MATCH"
    assert receipt["registrations"][0]["block_index"] == 1
    assert verify(chain, synthetic_document_hash(b"ALTERED SYNTHETIC FIXTURE"))["integrity"] == "MISMATCH"
    assert verify((genesis(cfg),), tx.document_hash)["integrity"] == "NOT_FOUND"
    conflict = transaction(cfg, document_hash="f" * 64, timestamp=150)
    fork = chain + (mine_next(chain, (conflict,), 200, cfg).block,)
    assert verify(fork, tx.document_hash)["integrity"] == "CONFLICT"
    broken = chain[:-1] + (replace(chain[-1], hash="0" * 64),)
    with pytest.raises(ValueError, match="invalid chain"):
        verify(broken, tx.document_hash)


def test_configuration_and_size_limits():
    with pytest.raises(ValueError):
        config(initial_difficulty=True)
    with pytest.raises(ValueError):
        config(max_difficulty=0)
    with pytest.raises(ValueError):
        synthetic_document_hash(b"x" * (1024 * 1024 + 1))
    cfg = config(max_transactions_per_block=1, max_chain_blocks=2)
    tx = transaction(cfg)
    with pytest.raises(ValueError):
        mine_next((genesis(cfg),), (tx, tx), 100, cfg)
    with pytest.raises(ValueError, match="chain limit"):
        mine_next(build(cfg, [100]), (), 200, cfg)
    assert not validate_chain((), cfg).valid
    assert block_work(2) == 256
