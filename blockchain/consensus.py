"""Pure fork choice only: this is not network propagation or distributed consensus."""
from .block import Block
from .config import NetworkConfig
from .validation import validate_chain


def choose_best_chain(candidates: tuple[tuple[Block, ...], ...],
                      config: NetworkConfig) -> tuple[Block, ...] | None:
    if type(candidates) is not tuple or len(candidates) > 32:
        raise ValueError("at most 32 bounded candidate chains")
    best = None
    best_rank = None
    for chain in candidates:
        result = validate_chain(chain, config)
        if not result.valid:
            continue
        rank = (-result.cumulative_work, chain[-1].hash)
        if best_rank is None or rank < best_rank:
            best, best_rank = chain, rank
    return best
