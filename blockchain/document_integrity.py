"""Local hash lookup over a valid chain. Does not prove authorship or legal validity."""
import hashlib
from .config import NetworkConfig
from .transaction import is_hash, is_uuid
from .validation import validate_chain


def synthetic_document_hash(document: bytes) -> str:
    # A caller-supplied byte string cannot be proved synthetic by its hash.
    # The future API must use a controlled synthetic fixture generator.
    if type(document) is not bytes or len(document) > 1024 * 1024:
        raise ValueError("document must be bytes, at most 1 MiB")
    return hashlib.sha256(document).hexdigest()


def verify_document_hash(chain, config: NetworkConfig, document_id: str, version_id: str,
                         supplied_hash: str) -> dict:
    if not is_uuid(document_id) or not is_uuid(version_id) or not is_hash(supplied_hash):
        raise ValueError("invalid document lookup")
    validation = validate_chain(chain, config)
    if not validation.valid:
        raise ValueError("cannot issue a receipt for an invalid chain")
    matches = []
    for block in chain:
        for tx in block.transactions:
            if (tx.document_id, tx.version_id) == (document_id, version_id):
                matches.append({"block_index": block.index, "block_hash": block.hash,
                                "tx_id": tx.tx_id, "timestamp": tx.timestamp,
                                "document_hash": tx.document_hash})
    distinct = {m["document_hash"] for m in matches}
    state = ("NOT_FOUND" if not matches else "CONFLICT" if len(distinct) > 1
             else "MATCH" if supplied_hash in distinct else "MISMATCH")
    return {"network_hash": config.fingerprint, "chain_tip": chain[-1].hash,
            "chain_valid": True, "supplied_hash": supplied_hash,
            "document_id": document_id, "version_id": version_id,
            "integrity": state, "registrations": matches,
            "limitation": "hash equality only; no identity, custody or legal certification"}
