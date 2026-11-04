import hashlib
from uuid import UUID
import pytest
from documents.qr import QRStore, AccessDenied

DOC = str(UUID(int=1, version=4))
VERSION = str(UUID(int=2, version=4))


def issue(store, max_uses=1):
    return store.issue(DOC, VERSION, 'a'*64, 'b'*64, 60, max_uses)


def test_qr_valid_reuse_restart_and_no_plaintext(tmp_path):
    path = tmp_path/'qr.sqlite3'
    store = QRStore(path, clock=lambda: 1000)
    grant = issue(store)
    assert grant['token'].encode() not in path.read_bytes()
    assert hashlib.sha256(grant['token'].encode()).hexdigest().encode() in path.read_bytes()
    result = store.resolve(grant['token'], lambda row: {'integrity': 'MATCH'})
    assert result['remaining_uses'] == 0
    with pytest.raises(AccessDenied):
        QRStore(path, clock=lambda: 1001).resolve(grant['token'], lambda row: {})


@pytest.mark.parametrize('case', ['expired', 'revoked', 'nonexistent', 'manipulated'])
def test_qr_denials_are_persistent_and_generic(tmp_path, case):
    clock = [1000]
    path = tmp_path/'qr.sqlite3'
    store = QRStore(path, clock=lambda: clock[0])
    grant = issue(store)
    token = grant['token']
    if case == 'expired':
        clock[0] = 1060
    elif case == 'revoked':
        assert store.revoke(token) and store.revoke(token)
    elif case == 'nonexistent':
        token = 'x'*43
    else:
        token = '../' + token
    with pytest.raises(AccessDenied, match='access unavailable'):
        store.resolve(token, lambda row: {})
    clock[0] = 1001
    with pytest.raises(AccessDenied):
        QRStore(path, clock=lambda: clock[0]).resolve(token, lambda row: {})


def test_unconfirmed_grant_does_not_consume_use(tmp_path):
    store = QRStore(tmp_path/'qr.sqlite3', clock=lambda: 1000)
    grant = issue(store)
    def unavailable(row):
        raise AccessDenied('access unavailable')
    with pytest.raises(AccessDenied):
        store.resolve(grant['token'], unavailable)
    assert store.resolve(grant['token'], lambda row: {'integrity': 'MATCH'})['remaining_uses'] == 0


def test_qr_bounds_and_corrupt_database(tmp_path):
    store = QRStore(tmp_path/'qr.sqlite3')
    for ttl, uses in ((59, 1), (3601, 1), (60, 0), (60, 11), (True, 1)):
        with pytest.raises(ValueError):
            store.issue(DOC, VERSION, 'a'*64, 'b'*64, ttl, uses)
    import sqlite3
    broken = tmp_path/'broken.sqlite3'
    broken.write_bytes(b'corrupt-original')
    with pytest.raises(sqlite3.DatabaseError):
        QRStore(broken)
    assert broken.read_bytes() == b'corrupt-original'
