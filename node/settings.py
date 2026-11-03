from pathlib import Path
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator
from blockchain.config import NetworkConfig

class Settings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    node_id: str = Field(pattern=r'^[a-z0-9-]{1,32}$')
    data_dir: str
    port: int = Field(ge=1024, le=65535)
    peers: list[str] = Field(default_factory=list, max_length=8)
    network: dict = Field(default_factory=dict)
    sync_interval_seconds: float = Field(default=3.0, ge=0.5, le=60)
    max_pending: int = Field(default=256, ge=1, le=1000)

    @field_validator('peers')
    @classmethod
    def validate_peers(cls, peers):
        clean = []
        for peer in peers:
            p = urlsplit(peer)
            if (p.scheme != 'http' or p.hostname != '127.0.0.1' or p.username or p.password
                    or p.path not in ('','/') or p.query or p.fragment or not p.port
                    or not 1024 <= p.port <= 65535):
                raise ValueError('phase 2 peers must be explicit loopback HTTP ports')
            normalized = f'http://127.0.0.1:{p.port}'
            if normalized not in clean:
                clean.append(normalized)
        return clean

    def config(self):
        return NetworkConfig(**self.network)

    def directory(self):
        return Path(self.data_dir).resolve()
