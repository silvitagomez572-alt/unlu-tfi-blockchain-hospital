"""Closed synthetic metadata schema. No document, free-text or signature fields yet."""
from dataclasses import asdict, dataclass, replace
import hashlib
from uuid import UUID
from .config import canonical_json

EVENTS = frozenset({"NOTE_RECEIVED", "DIRECTION_REVIEWED", "LEGAL_REVIEWED",
                    "VERSION_PREPARED", "QR_IDENTIFIER_ISSUED", "DELIVERY_RECORDED"})


def is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def is_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(UUID(value)) == value and UUID(value).version == 4
    except (ValueError, AttributeError):
        return False


@dataclass(frozen=True)
class Transaction:
    network_hash: str
    document_id: str
    version_id: str
    document_hash: str
    event_type: str
    timestamp: int
    actor_id: str
    previous_version_id: str | None = None
    previous_document_hash: str | None = None
    tx_id: str = ""

    def payload(self) -> dict:
        data = asdict(self)
        del data["tx_id"]
        return data

    def compute_id(self) -> str:
        return hashlib.sha256(canonical_json(self.payload())).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def create(cls, **fields) -> "Transaction":
        if "tx_id" in fields:
            raise ValueError("tx_id is calculated, not caller-supplied")
        tx = cls(**fields)
        tx = replace(tx, tx_id=tx.compute_id())
        validate_transaction(tx, tx.network_hash)
        return tx

    @classmethod
    def from_dict(cls, data: dict) -> "Transaction":
        if type(data) is not dict or set(data) != set(cls.__dataclass_fields__):
            raise ValueError("unexpected/missing transaction fields")
        tx = cls(**data)
        validate_transaction(tx, tx.network_hash)
        return tx


def validate_transaction(tx: Transaction, network_hash: str) -> None:
    if type(tx) is not Transaction:
        raise ValueError("expected Transaction")
    if not is_hash(tx.network_hash) or tx.network_hash != network_hash:
        raise ValueError("transaction belongs to another network")
    if not all(is_uuid(v) for v in (tx.document_id, tx.version_id, tx.actor_id)):
        raise ValueError("identifiers must be canonical random UUIDv4")
    if not is_hash(tx.document_hash) or not is_hash(tx.tx_id):
        raise ValueError("invalid transaction hash")
    if type(tx.event_type) is not str or tx.event_type not in EVENTS:
        raise ValueError("unknown event")
    if type(tx.timestamp) is not int or not 0 <= tx.timestamp <= 2**63 - 1:
        raise ValueError("timestamp must be integer milliseconds")
    if (tx.previous_version_id is None) != (tx.previous_document_hash is None):
        raise ValueError("previous version and hash must be paired")
    if tx.previous_version_id is not None:
        if not is_uuid(tx.previous_version_id) or not is_hash(tx.previous_document_hash):
            raise ValueError("invalid version reference")
        if tx.previous_version_id == tx.version_id:
            raise ValueError("version cannot reference itself")
    if tx.compute_id() != tx.tx_id:
        raise ValueError("transaction id mismatch")
