from functools import lru_cache
from .block import Block, ZERO_HASH
from .config import NetworkConfig
from .mining import mine


@lru_cache(maxsize=8)
def genesis(config: NetworkConfig) -> Block:
    """Same parameters, same first valid nonce. Cache avoids remine per validation."""
    candidate = Block(0, ZERO_HASH, (), config.genesis_timestamp,
                      config.initial_difficulty, config.fingerprint)
    return mine(candidate, max_attempts=1_000_000, timeout_seconds=10,
                max_nonce=config.max_nonce).block
