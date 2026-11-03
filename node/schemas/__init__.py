from pydantic import BaseModel, ConfigDict, Field
from blockchain.transaction import Transaction

HEX = r'^[0-9a-f]{64}$'
UUID = r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'

class TxRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    network_hash: str = Field(pattern=HEX)
    document_id: str = Field(pattern=UUID)
    version_id: str = Field(pattern=UUID)
    document_hash: str = Field(pattern=HEX)
    event_type: str = Field(max_length=32)
    timestamp: int = Field(ge=0, le=2**63-1)
    actor_id: str = Field(pattern=UUID)
    previous_version_id: str | None = Field(default=None, pattern=UUID)
    previous_document_hash: str | None = Field(default=None, pattern=HEX)
    tx_id: str | None = Field(default=None, pattern=HEX)

    def transaction(self):
        data = self.model_dump()
        if data.pop('tx_id') is None:
            return Transaction.create(**data)
        return Transaction.from_dict(self.model_dump())

class BlockRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    index: int = Field(ge=0, le=100_000)
    previous_hash: str = Field(pattern=HEX)
    transactions: list[TxRequest] = Field(max_length=1000)
    timestamp: int = Field(ge=0, le=2**63-1)
    difficulty: int = Field(ge=1, le=6)
    network_hash: str = Field(pattern=HEX)
    nonce: int = Field(ge=0, le=2**63-1)
    hash: str = Field(pattern=HEX)

class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    document_id: str = Field(pattern=UUID)
    version_id: str = Field(pattern=UUID)
    document_hash: str = Field(pattern=HEX)

class SyntheticRegister(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    fixture_id: int = Field(ge=1, le=10000)
    document_id: str = Field(pattern=UUID)
    version_id: str = Field(pattern=UUID)
    actor_id: str = Field(pattern=UUID)
