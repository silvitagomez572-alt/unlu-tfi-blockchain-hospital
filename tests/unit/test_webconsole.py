import re
from fastapi.testclient import TestClient
from documents.app import create_document_app
from documents.rules import fixture_hash
from test_documents import options, uid
from test_document_api import keys


def test_console_entry_navigation_security(tmp_path):
    opts = options(tmp_path).model_copy(update={'console': True})
    origin = f'http://127.0.0.1:{opts.port}'
    with TestClient(create_document_app(opts, keys()), base_url=origin) as client:
        navigation = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
        page = client.get('/console/', headers=navigation)
        assert page.status_code == 200
        csrf = re.search(r'name="hisjb-csrf" content="([A-Za-z0-9_-]+)"', page.text).group(1)
        assert client.get('/console/api/summary', headers=navigation | {'X-HISJB-CSRF': csrf}).status_code == 403
        assert client.get('/console/api/summary', headers={'X-HISJB-CSRF': csrf, 'Origin': origin}).status_code == 200
        assert client.get('/console/', headers={'Host': 'attacker.invalid'}).status_code == 403


def test_console_live_backend_and_security(tmp_path):
    opts = options(tmp_path).model_copy(update={'console': True})
    credentials = keys()
    app = create_document_app(opts, credentials)
    origin = f'http://127.0.0.1:{opts.port}'
    with TestClient(app, base_url=origin) as client:
        assert client.get('/console/api/summary').status_code == 403
        page = client.get('/console/')
        assert page.status_code == 200 and 'HISJB Evidence Chain' in page.text
        assert client.get('/console/', headers={'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                                               'Sec-Fetch-Dest': 'document'}).status_code == 200
        assert not any(secret in page.text for secret in credentials.values())
        csrf = re.search(r'name="hisjb-csrf" content="([A-Za-z0-9_-]+)"', page.text).group(1)
        headers = {'X-HISJB-CSRF': csrf, 'Origin': origin}
        assert client.get('/console/assets/../../state.json').status_code != 200
        assert client.get('/console/', headers={'Host': 'attacker.invalid'}).status_code == 403
        assert client.get('/console/api/summary', headers=headers | {'Origin': 'https://attacker.invalid'}).status_code == 403
        assert client.get('/console/api/summary', headers=headers | {'Sec-Fetch-Site': 'cross-site'}).status_code == 403
        assert client.get('/console/api/summary', headers=headers).json()['height'] == 0
        assert client.post('/console/api/command', json={'action': 'mine', 'role': 'operator'}).status_code == 403
        def command(action, role, payload=None):
            return client.post('/console/api/command', headers=headers,
                               json={'action': action, 'role': role, 'payload': payload or {}})
        body = {'document_id': uid(1), 'version_id': uid(101), 'fixture_id': 1}
        registered = command('register', 'mesa', body)
        assert registered.status_code == 202
        assert client.get('/console/api/summary', headers=headers).json()['pending_transactions'] == 1
        mined = command('mine', 'operator')
        assert mined.status_code == 200 and mined.json()['attempts'] >= 1
        summary = client.get('/console/api/summary', headers=headers).json()
        assert summary['height'] == 1 and summary['confirmed_transactions'] == 1
        assert summary['last_mining']['hash'] == mined.json()['block']['hash']
        block = client.get('/console/api/block/1', headers=headers).json()
        assert block['transactions'][0]['tx_id'] == registered.json()['transaction_id']
        assert len(client.get('/console/api/history/'+uid(1), headers=headers).json()) == 1
        for digest, expected in ((fixture_hash(1), 'MATCH'), ('a'*64, 'MISMATCH')):
            verified = command('verify', 'auditor', {'document_id': uid(1), 'version_id': uid(101), 'document_hash': digest})
            assert verified.json()['integrity'] == expected
        assert command('mine', 'auditor').status_code == 403
        assert command('not-a-real-action', 'operator').status_code == 422
        assert len(client.get('/console/api/nodes', headers=headers).json()['nodes']) == 1
        before = app.state.node.snapshot()
    with TestClient(create_document_app(opts, credentials), base_url=origin) as client:
        assert client.app.state.node.snapshot() == before
