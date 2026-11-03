"""Structural/PoW validation plus exact replay rejection; no authorization claims."""
from dataclasses import dataclass
from .block import Block, ZERO_HASH
from .config import NetworkConfig
from .difficulty import block_work, next_difficulty
from .genesis import genesis
from .transaction import is_hash, validate_transaction


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str
    cumulative_work: int = 0


def validate_chain(chain: tuple[Block, ...], config: NetworkConfig) -> ValidationResult:
    if type(chain) is not tuple or not 1 <= len(chain) <= config.max_chain_blocks:
        return ValidationResult(False, "chain must be a bounded non-empty tuple")
    seen = set()
    work = 0
    prefix = []
    for index, block in enumerate(chain):
        try:
            if type(block) is not Block or type(block.index) is not int or block.index != index:
                raise ValueError("invalid block/index")
            if type(block.nonce) is not int or not 0 <= block.nonce <= config.max_nonce:
                raise ValueError("invalid nonce")
            if type(block.timestamp) is not int or not 0 <= block.timestamp <= 2**63 - 1:
                raise ValueError("invalid timestamp")
            if index and block.timestamp <= prefix[-1].timestamp:
                raise ValueError("timestamps must increase")
            if type(block.difficulty) is not int or block.difficulty != next_difficulty(prefix, config):
                raise ValueError("difficulty disagrees with network rule")
            if block.network_hash != config.fingerprint:
                raise ValueError("network mismatch")
            if not is_hash(block.hash) or not is_hash(block.previous_hash):
                raise ValueError("invalid hash representation")
            expected = ZERO_HASH if index == 0 else prefix[-1].hash
            if block.previous_hash != expected:
                raise ValueError("broken link")
            if type(block.transactions) is not tuple or len(block.transactions) > config.max_transactions_per_block:
                raise ValueError("invalid transaction collection")
            for tx in block.transactions:
                validate_transaction(tx, config.fingerprint)
                if not config.genesis_timestamp <= tx.timestamp <= block.timestamp:
                    raise ValueError("transaction timestamp outside chain history")
                if tx.tx_id in seen:
                    raise ValueError("replayed transaction")
                seen.add(tx.tx_id)
            if block.compute_hash() != block.hash:
                raise ValueError("hash mismatch")
            if not block.hash.startswith("0" * block.difficulty):
                raise ValueError("insufficient proof of work")
            if index == 0 and block != genesis(config):
                raise ValueError("non-canonical genesis")
            work += block_work(block.difficulty)
            prefix.append(block)
        except (ValueError, TypeError, OverflowError, RecursionError) as exc:
            return ValidationResult(False, f"block {index}: {exc}")
    return ValidationResult(True, "valid protocol-v1 chain", work)
