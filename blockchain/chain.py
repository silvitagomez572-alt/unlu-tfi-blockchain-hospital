"""Immutable local chain operations. Networking and persistence remain separate."""
from .block import Block
from .config import NetworkConfig
from .difficulty import next_difficulty
from .mining import MiningResult, mine
from .transaction import Transaction, validate_transaction
from .validation import validate_chain


def mine_next(chain: tuple[Block, ...], transactions: tuple[Transaction, ...],
              timestamp: int, config: NetworkConfig, **budget) -> MiningResult:
    state = validate_chain(chain, config)
    if not state.valid:
        raise ValueError(state.reason)
    if len(chain) >= config.max_chain_blocks:
        raise ValueError("chain limit reached")
    if type(timestamp) is not int or not chain[-1].timestamp < timestamp <= 2**63 - 1:
        raise ValueError("timestamp must increase")
    if type(transactions) is not tuple or len(transactions) > config.max_transactions_per_block:
        raise ValueError("invalid transaction collection")
    seen = {tx.tx_id for block in chain for tx in block.transactions}
    for tx in transactions:
        validate_transaction(tx, config.fingerprint)
        if tx.tx_id in seen:
            raise ValueError("replayed transaction")
        if not config.genesis_timestamp <= tx.timestamp <= timestamp:
            raise ValueError("transaction timestamp outside chain history")
        seen.add(tx.tx_id)
    candidate = Block(len(chain), chain[-1].hash, transactions, timestamp,
                      next_difficulty(chain, config), config.fingerprint)
    return mine(candidate, max_nonce=config.max_nonce, **budget)
