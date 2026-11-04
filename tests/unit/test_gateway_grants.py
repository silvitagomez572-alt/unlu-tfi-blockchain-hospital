from uuid import UUID
import pytest
from gateway.grants import GrantStore,GrantDenied

DOC=str(UUID(int=1,version=4)); VERSION=str(UUID(int=2,version=4)); HASH='a'*64

def test_grant_survives_restart_and_stores_only_digest(tmp_path):
    path=tmp_path/'grants.sqlite3'; store=GrantStore(path,clock=lambda:1000)
    grant=store.issue(DOC,VERSION,HASH,60)
    assert grant['token'].encode() not in path.read_bytes()
    recovered=GrantStore(path,clock=lambda:1001)
    assert recovered.resolve(grant['token'])=={'document_id':DOC,'version_id':VERSION,'document_hash':HASH}

def test_expiry_is_sticky_after_clock_rollback(tmp_path):
    clock=[1000]; store=GrantStore(tmp_path/'grants.sqlite3',clock=lambda:clock[0])
    grant=store.issue(DOC,VERSION,HASH,60); clock[0]=1060
    with pytest.raises(GrantDenied): store.resolve(grant['token'])
    clock[0]=1001
    with pytest.raises(GrantDenied): store.resolve(grant['token'])

def test_revocation_is_persistent_and_idempotent(tmp_path):
    path=tmp_path/'grants.sqlite3'; store=GrantStore(path,clock=lambda:1000)
    grant=store.issue(DOC,VERSION,HASH,60)
    assert store.revoke(grant['grant_id']) and store.revoke(grant['grant_id'])
    with pytest.raises(GrantDenied): GrantStore(path,clock=lambda:1001).resolve(grant['token'])

def test_token_and_ttl_validation(tmp_path):
    store=GrantStore(tmp_path/'grants.sqlite3',clock=lambda:1000)
    for ttl in (0,59,3601,True):
        with pytest.raises(ValueError): store.issue(DOC,VERSION,HASH,ttl)
    for token in ('','wrong','a'*43):
        with pytest.raises(GrantDenied): store.resolve(token)
