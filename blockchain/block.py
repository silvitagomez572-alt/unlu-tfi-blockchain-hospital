"""Adapted from Lab 8 Block: immutable, with difficulty and network commitment."""
from dataclasses import asdict, dataclass
import hashlib
from .config import canonical_json
from .transaction import Transaction

ZERO_HASH = "0" * 64


@dataclass(frozen=True)
class Block:
    index: int
    previous_hash: str
    transactions: tuple[Transaction, ...]
    timestamp: int
    difficulty: int
    network_hash: str
    nonce: int = 0
    hash: str = ""

    def header(self) -> bytes:
        # Preserve the template's canonical JSON + nonce construction.
        payload = asdict(self)
        del payload["hash"]
        del payload["nonce"]
        return canonical_json(payload)

    def compute_hash(self, nonce: int | None = None) -> str:
        n = self.nonce if nonce is None else nonce
        return hashlib.sha256(self.header() + str(n).encode("ascii")).hexdigest()

    def to_dict(self) -> dict:
        result = asdict(self)
        result["transactions"] = [t.to_dict() for t in self.transactions]
        return result

    @classmethod
    def from_dict(cls, data: dict, *, max_transactions: int = 100) -> "Block":
        if type(data) is not dict or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("unexpected/missing block fields")
        txs = data["transactions"]
        if type(txs) is not list or len(txs) > max_transactions:
            raise ValueError("invalid transaction collection")
        return cls(**(data | {"transactions": tuple(Transaction.from_dict(t) for t in txs)}))
