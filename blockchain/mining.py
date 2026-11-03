"""Bounded nonce search; caller decides whether to commit the immutable result."""
from dataclasses import dataclass, replace
import hashlib
import time
from .block import Block


class MiningBudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class MiningResult:
    block: Block
    elapsed_seconds: float
    attempts: int


def mine(block: Block, *, max_attempts: int = 100_000,
         timeout_seconds: float = 1.0, max_nonce: int = 2**63 - 1) -> MiningResult:
    if type(max_attempts) is not int or not 1 <= max_attempts <= 1_000_000:
        raise ValueError("invalid attempt budget")
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 10:
        raise ValueError("invalid time budget")
    if type(block.difficulty) is not int or not 1 <= block.difficulty <= 6:
        raise ValueError("invalid difficulty")
    if type(block.nonce) is not int or not 0 <= block.nonce <= max_nonce <= 2**63 - 1:
        raise ValueError("invalid nonce")
    header = block.header()
    target = "0" * block.difficulty
    started = time.perf_counter()
    for attempt in range(max_attempts):
        nonce = block.nonce + attempt
        elapsed = time.perf_counter() - started
        if elapsed >= timeout_seconds or nonce > max_nonce:
            break
        digest = hashlib.sha256(header + str(nonce).encode("ascii")).hexdigest()
        if digest.startswith(target):
            return MiningResult(replace(block, nonce=nonce, hash=digest),
                                time.perf_counter() - started, attempt + 1)
    raise MiningBudgetExceeded("nonce/time budget exhausted; input not mutated")
