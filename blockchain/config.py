"""Consensus parameters: changing these creates another network identity."""
from dataclasses import asdict, dataclass
import hashlib
import json


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


@dataclass(frozen=True)
class NetworkConfig:
    network_id: str = "unlu-hospital-synthetic-v1"
    protocol_version: int = 1
    initial_difficulty: int = 1
    min_difficulty: int = 1
    max_difficulty: int = 4
    target_interval_ms: int = 10_000
    retarget_window: int = 4
    genesis_timestamp: int = 0
    max_transactions_per_block: int = 100
    max_chain_blocks: int = 10_000
    max_nonce: int = 2**63 - 1

    def __post_init__(self):
        if not isinstance(self.network_id, str) or not 1 <= len(self.network_id) <= 64:
            raise ValueError("invalid network_id")
        if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in self.network_id):
            raise ValueError("network_id must be lowercase ASCII")
        for key, value in asdict(self).items():
            if key != "network_id" and (type(value) is not int or value < 0):
                raise ValueError(f"invalid integer parameter: {key}")
        if self.protocol_version != 1:
            raise ValueError("unsupported protocol")
        if not 1 <= self.min_difficulty <= self.initial_difficulty <= self.max_difficulty <= 6:
            raise ValueError("invalid difficulty range")
        if self.initial_difficulty > 3:
            raise ValueError("initial difficulty exceeds bounded genesis budget")
        if not 2 <= self.retarget_window <= 1024 or self.target_interval_ms < 1:
            raise ValueError("invalid retarget parameters")
        if not 1 <= self.max_transactions_per_block <= 1000:
            raise ValueError("invalid transaction bound")
        if not 2 <= self.max_chain_blocks <= 100_000 or not 1 <= self.max_nonce <= 2**63 - 1:
            raise ValueError("invalid chain bound")

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self))).hexdigest()
