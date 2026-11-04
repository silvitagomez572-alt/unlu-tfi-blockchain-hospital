import secrets
import sqlite3
import xml.etree.ElementTree as ET
from fastapi.testclient import TestClient
from documents.app import create_document_app
from documents.security import KEY_ROLES
from documents.rules import fixture_hash
from node.state import NodeError
from test_documents import options, uid, confirmed, entry


def keys():
    return {role: secrets.token_urlsafe(32) for role in KEY_ROLES}


def auth(credentials, role):
    return {'Authorization': 'Bearer '+credentials[role]}


def post(client, credentials, role, path, body=None):
    return client.post(path, headers=auth(credentials, role), json=body)


def mine(client, credentials):
    assert post(client, credentials, 'operator', '/mine').status_code == 200


def test_api_two_versions_and_qr_use_revocation_restart(tmp_path):
    credentials = keys()
    opts = options(tmp_path)
    app = create_document_app(opts, credentials)
    with TestClient(app) as client:
        for version in (101, 102):
            body = {'document_id': uid(1), 'version_id': uid(version), 'fixture_id': version-100}
            path = '/documents/register'
            if version == 102:
                path = '/documents/versions'
                body |= {'previous_version_id': uid(101), 'previous_version_hash': fixture_hash(1)}
            response = post(client, credentials, 'mesa', path, body)
            assert response.status_code == 202
            assert response.json()['metadata']['synthetic'] is True
            assert post(client, credentials, 'mesa', path, body).status_code == 409
            mine(client, credentials)
            for role, event in (('direccion', 'DIRECTION_REVIEWED'), ('legal', 'LEGAL_REVIEWED'), ('bio', 'VERSION_PREPARED')):
                assert post(client, credentials, role, '/documents/events', {
                    'document_id': uid(1), 'version_id': uid(version), 'event_type': event}).status_code == 202
                mine(client, credentials)
            qr = post(client, credentials, 'bio', '/qr/create', {
                'document_id': uid(1), 'version_id': uid(version), 'max_uses': 2})
            assert qr.status_code == 202
            grant = qr.json()
            assert ET.fromstring(grant['qr_svg']).tag.endswith('svg')
            assert uid(1) not in grant['url'] and fixture_hash(version-100) not in grant['url']
            url = '/qr/'+grant['token']
            assert client.get(url, headers=auth(credentials, 'auditor')).status_code == 403  # unconfirmed
            mine(client, credentials)
            read = client.get(url, headers=auth(credentials, 'auditor'))
            assert read.status_code == 200 and read.json()['verification']['integrity'] == 'MATCH'
            assert read.headers['cache-control'] == 'no-store'
            if version == 101:
                assert client.get(url, headers=auth(credentials, 'auditor')).json()['remaining_uses'] == 0
                assert client.get(url, headers=auth(credentials, 'auditor')).status_code == 403
            else:
                revoked_url = url
                assert post(client, credentials, 'bio', url+'/revoke').status_code == 204
                assert client.get(url, headers=auth(credentials, 'auditor')).status_code == 403
            assert post(client, credentials, 'bio', '/documents/events', {
                'document_id': uid(1), 'version_id': uid(version), 'event_type': 'DELIVERY_RECORDED'}).status_code == 202
            mine(client, credentials)
        history = client.get('/documents/'+uid(1)+'/history', headers=auth(credentials, 'auditor')).json()
        assert len(history) == 12 and history[-1]['previous_version_hash'] == fixture_hash(1)
        chain = app.state.node.snapshot()
        for value, outcome in ((fixture_hash(2), 'MATCH'), ('a'*64, 'MISMATCH')):
            verified = post(client, credentials, 'auditor', '/documents/verify', {
                'document_id': uid(1), 'version_id': uid(102), 'document_hash': value})
            assert verified.json()['integrity'] == outcome
            assert verified.json()['hash_calculated'] is None
        missing = post(client, credentials, 'auditor', '/documents/verify', {
            'document_id': uid(1), 'version_id': uid(999), 'document_hash': fixture_hash(2)})
        assert missing.json()['integrity'] == 'NOT_FOUND'
    with TestClient(create_document_app(opts, credentials)) as client:
        assert client.app.state.node.snapshot() == chain
        assert client.get(revoked_url, headers=auth(credentials, 'auditor')).status_code == 403


def test_api_access_schema_rate_limit_and_peer_bypass(tmp_path):
    credentials = keys()
    app = create_document_app(options(tmp_path), credentials)
    with TestClient(app) as client:
        assert client.get('/chain').status_code == 401
        assert post(client, credentials, 'auditor', '/mine').status_code == 403
        body = {'document_id': uid(1), 'version_id': uid(101), 'fixture_id': 1}
        assert post(client, credentials, 'legal', '/documents/register', body).status_code == 403
        assert post(client, credentials, 'mesa', '/documents/register', body | {'patient_name': 'NOT_ALLOWED'}).status_code == 422
        assert post(client, credentials, 'mesa', '/documents/register', body | {'document_id': '../state.json'}).status_code == 422
        assert post(client, credentials, 'mesa', '/documents/register', body | {'metadata': {'free_text': 'NOT_ALLOWED'}}).status_code == 422
        assert client.post('/documents/register', headers=auth(credentials, 'mesa'), content=b'x'*65537).status_code == 413
        bad = entry(app.state.node, 3)
        assert post(client, credentials, 'mesa', '/transactions', bad.to_dict()).status_code == 403
        assert post(client, credentials, 'peer', '/transactions', bad.to_dict()).status_code == 409
        assert post(client, credentials, 'peer', '/qr/create', {}).status_code == 403
        assert len(app.state.node.snapshot()[0]) == 1 and not app.state.node.pending
    with TestClient(create_document_app(options(tmp_path), credentials, rate_limit=2)) as client:
        for _ in range(2):
            assert client.get('/chain', headers=auth(credentials, 'auditor')).status_code == 200
        assert client.get('/chain', headers=auth(credentials, 'auditor')).status_code == 429


def test_qr_api_expiry_and_partial_write_fail_closed(tmp_path, monkeypatch):
    credentials = keys()
    clock = [1000]
    app = create_document_app(options(tmp_path), credentials, qr_clock=lambda: clock[0])
    with TestClient(app) as client:
        state = app.state.node
        for stage in range(4):
            confirmed(state, stage)
        original = state.add_transaction
        def fail(tx):
            raise NodeError(503, 'injected failure')
        monkeypatch.setattr(state, 'add_transaction', fail)
        body = {'document_id': uid(1), 'version_id': uid(101), 'ttl_seconds': 60}
        assert post(client, credentials, 'bio', '/qr/create', body).status_code == 503
        with sqlite3.connect(tmp_path/'qr.sqlite3') as db:
            assert db.execute('SELECT count(*) FROM grants WHERE revoked=1').fetchone()[0] == 1
        assert not state.pending
        monkeypatch.setattr(state, 'add_transaction', original)
        qr = post(client, credentials, 'bio', '/qr/create', body)
        assert qr.status_code == 202
        url = '/qr/'+qr.json()['token']
        mine(client, credentials)
        clock[0] = 1060
        assert client.get(url, headers=auth(credentials, 'auditor')).status_code == 403
        clock[0] = 1001
        assert client.get(url, headers=auth(credentials, 'auditor')).status_code == 403
