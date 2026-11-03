"""Deterministic retarget from committed timestamps, never local mining duration."""
from collections.abc import Sequence
from .block import Block
from .config import NetworkConfig


def next_difficulty(prefix: Sequence[Block], config: NetworkConfig) -> int:
    if not prefix:
        return config.initial_difficulty
    next_index = len(prefix)
    last = prefix[-1]
    window = config.retarget_window
    # At height W+1 there are W complete intervals after the genesis.
    if next_index <= window or (next_index - 1) % window != 0:
        return last.difficulty
    elapsed = last.timestamp - prefix[-1 - window].timestamp
    expected = window * config.target_interval_ms
    if elapsed * 2 < expected:
        return min(config.max_difficulty, last.difficulty + 1)
    if elapsed > expected * 2:
        return max(config.min_difficulty, last.difficulty - 1)
    return last.difficulty


def block_work(difficulty: int) -> int:
    if type(difficulty) is not int or not 1 <= difficulty <= 6:
        raise ValueError("invalid difficulty")
    # Target = 2**(256 - 4*d). Expected trials = 2**256 / target.
    return 16**difficulty
