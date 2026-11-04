"""Real Chromium E2E against the unchanged HISJB console, inside its netns.

Do not record traces/HAR/cookies/QR images: those could expose session or QR
credentials. Save selective public API responses and screenshots after revoke.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/container-validation'
PRIVATE = ROOT / '.runtime/container-validation'
BASE = 'http://127.0.0.1:19980'
CREDS = json.loads((PRIVATE / 'credentials.json').read_text())
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PHASE = sys.argv[1]
assert PHASE in ('before', 'after')
CHECKS = []
STAGE = 'health'


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def request(path, role=None, headers=None):
    h = {} if headers is None else dict(headers)
    if role:
        h['Authorization'] = 'Bearer ' + CREDS[role]
    try:
        with HTTP.open(urllib.request.Request(BASE + path, headers=h), timeout=3) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def public_json(path, role='auditor'):
    code, body = request(path, role)
    assert code == 200, f'public read failed ({code})'
    return json.loads(body)


def check(name, condition, **data):
    assert condition, name
    CHECKS.append({'check': name, 'status': 'PASS', 'utc': datetime.now(timezone.utc).isoformat(), **data})
    save(f'checks-{PHASE}.json', CHECKS)


def run():
    global STAGE
    deadline = time.monotonic() + 25
    while True:
        try:
            health = public_json('/healthz', None)
            break
        except (OSError, AssertionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.5)
    save(f'health-{PHASE}.json', health)
    check('health', health['status'] == 'ok' and health['node_id'] == 'hisjb-0')
    check('unauthenticated direct chain denied', request('/chain')[0] == 401)
    check('missing console session/CSRF denied', request('/console/api/summary')[0] == 403)
    check('wrong Host denied', request('/console/', headers={'Host': 'example.invalid'})[0] == 403)
    check('wrong Origin denied', request('/console/', headers={'Origin': 'https://example.invalid'})[0] == 403)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
        try:
            context = browser.new_context(viewport={'width': 1440, 'height': 1080}, locale='es-AR', timezone_id='America/Argentina/Buenos_Aires')
            page = context.new_page()
            page.set_default_timeout(10000)
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
            response = page.goto(BASE + '/console/', wait_until='networkidle')
            check('frontend HTTP 200', response.status == 200)
            expect(page.locator('#connection')).to_have_text('API conectada')
            expect(page.locator('#stat-nodes')).to_have_text('1 / 1')
            expect(page.locator('#fixture-hash')).to_have_value(hashlib.sha256(b'UNLU-SYNTHETIC-FIXTURE-00001').hexdigest())
            save(f'browser-environment-{PHASE}.json', {'browser': browser.version, 'url': page.url,
                'navigator_language': page.evaluate('navigator.language'),
                'LANG': os.environ.get('LANG'), 'LC_ALL': os.environ.get('LC_ALL'),
                'capture_environment': 'Docker + Chromium on GitHub runner, NOT Edge on Windows or GKE'})

            def view(name):
                page.locator('button.nav[data-view="' + name + '"]').click()
                expect(page.locator('#view-' + name)).to_be_visible()

            def shot(name):
                # Only screenshots from live browser pixels; no HTML edits/overlays.
                assert page.locator('.qr-image').count() == 0, 'Never capture a QR capability'
                page.screenshot(path=str(OUT / name), full_page=True)

            def action(selector, action_name, status):
                started = time.perf_counter()
                with page.expect_response(lambda r: r.url == BASE + '/console/api/command'
                    and r.request.method == 'POST' and r.request.post_data_json.get('action') == action_name) as pending:
                    page.locator(selector).click()
                response = pending.value
                assert response.status == status, f'{action_name}: HTTP {response.status}, expected {status}'
                CHECKS.append({'check': action_name, 'status': 'PASS', 'http': response.status,
                               'response_observed_seconds': time.perf_counter() - started,
                               'utc': datetime.now(timezone.utc).isoformat()})
                save(f'checks-{PHASE}.json', CHECKS)
                expect(page.locator(selector)).to_be_enabled()
                return None if status == 204 else response.json()

            def mine():
                view('mining')
                mined = action('#mine-button', 'mine', 200)
                expect(page.locator('#mining-result')).to_contain_text('Bloque #' + str(mined['block']['index']) + ' minado')
                check('actual PoW attempts and duration', mined['attempts'] > 0 and mined['elapsed_seconds'] >= 0,
                      block=mined['block']['index'], attempts=mined['attempts'], elapsed_seconds=mined['elapsed_seconds'])
                save('mined-' + str(mined['block']['index']) + '.json', mined)
                return mined

            if PHASE == 'before':
                STAGE = 'register'
                shot('01_DASHBOARD_REAL.png')
                view('register')
                document = page.locator('#document-id').input_value()
                version = page.locator('#version-id').input_value()
                registered = action('#event-form button[type="submit"]', 'register', 202)
                save('registered-event.json', registered)
                expect(page.locator('#registration-result')).to_contain_text('Transacción recibida')
                shot('02_REGISTRO_PENDIENTE.png')
                view('dashboard')
                expect(page.locator('#stat-pending')).to_have_text('1')
                shot('03_MEMPOOL_REAL.png')
                STAGE = 'mine'
                first = mine()
                check('transaction included in block', first['block']['transactions'][0]['tx_id'] == registered['transaction_id'])
                shot('04_MINERIA_REAL.png')
                view('blocks')
                expect(page.locator('#block-detail')).to_contain_text(first['block']['hash'])
                shot('05_BLOQUE_REAL.png')
                STAGE = 'integrity'
                view('verify')
                good = action('#verify-form button[type="submit"], #verify-form button.primary', 'verify', 200)
                check('unaltered synthetic document MATCH', good['integrity'] == 'MATCH')
                save('integrity-match.json', good)
                expect(page.locator('#verify-result')).to_contain_text('Integridad verificada')
                shot('06_INTEGRIDAD_MATCH.png')
                page.locator('#alter-hash').click()
                expect(page.locator('#alter-hash')).to_be_enabled()
                bad = action('#verify-form button.primary', 'verify', 200)
                check('altered copy MISMATCH', bad['integrity'] == 'MISMATCH')
                save('integrity-mismatch.json', bad)
                expect(page.locator('#verify-result')).to_contain_text('Alteración detectada')
                shot('07_ALTERACION_DETECTADA.png')
                STAGE = 'administrative circuit'
                for event in ('DIRECTION_REVIEWED', 'LEGAL_REVIEWED', 'VERSION_PREPARED'):
                    view('register')
                    page.locator('#operation').select_option(event)
                    record = action('#event-form button[type="submit"]', 'event', 202)
                    check(event, record['event_type'] == event)
                    mine()
                STAGE = 'QR'
                view('qr')
                grant = action('#qr-form button.primary', 'qr_create', 202)
                token = grant['token']
                # Only a private ephemeral file carries the QR capability across restart.
                private = PRIVATE / 'qr-private.json'
                private.write_text(json.dumps({'token': token, 'document': document, 'version': version}))
                private.chmod(0o600)
                mine()
                view('qr')
                resolved = action('#qr-read', 'qr_read', 200)
                check('QR authorized read', resolved['verification']['integrity'] == 'MATCH')
                action('#qr-revoke', 'qr_revoke', 204)
                expect(page.locator('#qr-result')).to_contain_text('Acceso revocado')
                denied = action('#qr-read', 'qr_read', 403)
                check('QR access denied after revoke', denied['detail'] == 'access unavailable')
                shot('08_QR_REVOCADO.png')
                view('register')
                page.locator('#operation').select_option('DELIVERY_RECORDED')
                action('#event-form button[type="submit"]', 'event', 202)
                mine()
                STAGE = 'document version'
                view('register')
                page.locator('#operation').select_option('version')
                page.locator('#fixture').select_option('2')
                expect(page.locator('#fixture-hash')).to_have_value(hashlib.sha256(b'UNLU-SYNTHETIC-FIXTURE-00002').hexdigest())
                v2 = action('#event-form button[type="submit"]', 'version', 202)
                check('version links original', v2['version_id'] != version)
                mine()
                view('verify')
                with page.expect_response(lambda r: r.url.endswith('/console/api/history/' + document)) as history_response:
                    page.locator('#history-form button').click()
                history = history_response.value.json()
                check('history has both versions', len({row['version_id'] for row in history}) == 2 and len(history) == 7)
                save('document-history.json', history)
                expect(page.locator('#history-list li')).to_have_count(7)
                shot('09_HISTORIAL_VERSIONES.png')
                STAGE = 'nodes'
                view('network')
                synchronized = action('#sync-button', 'sync', 200)
                check('honest isolated-node state', synchronized['state'] == 'isolated')
                shot('10_NODO_AISLADO.png')
                # Leave one real pending event to verify mempool recovery as well.
                view('register')
                page.locator('#operation').select_option('register')
                page.locator('#new-identifiers').click()
                action('#event-form button[type="submit"]', 'register', 202)
                view('dashboard')
                expect(page.locator('#stat-height')).to_have_text('7')
                expect(page.locator('#stat-pending')).to_have_text('1')
                shot('11_DASHBOARD_ANTES_REINICIO.png')
                save('chain-before.json', public_json('/chain'))
                save('pending-before.json', public_json('/transactions/pending'))
                for file in OUT.rglob('*'):
                    if file.is_file():
                        assert token.encode() not in file.read_bytes(), 'QR capability in artifact'
            else:
                STAGE = 'recovery'
                old_chain = json.loads((OUT / 'chain-before.json').read_text())
                old_pending = json.loads((OUT / 'pending-before.json').read_text())
                chain = public_json('/chain')
                pending = public_json('/transactions/pending')
                check('full chain recovered', chain == old_chain, tip=chain['tip'])
                check('full mempool recovered', pending == old_pending and len(pending) == 1)
                save('chain-after.json', chain)
                save('pending-after.json', pending)
                private = json.loads((PRIVATE / 'qr-private.json').read_text())
                code, _ = request('/qr/' + private['token'], 'auditor')
                check('QR revocation survived restart', code == 403)
                expect(page.locator('#stat-height')).to_have_text('7')
                expect(page.locator('#stat-pending')).to_have_text('1')
                expect(page.locator('#validation-pill')).to_have_text('Cadena validada')
                shot('12_PERSISTENCIA_REINICIO.png')
            check('no unhandled browser JavaScript error', not errors)
            code, metrics = request('/metrics')
            check('Prometheus metrics endpoint', code == 200 and b'pow_block_height 7.0' in metrics)
            (OUT / f'metrics-{PHASE}.txt').write_bytes(metrics)
            context.close()
        finally:
            browser.close()
    save(f'browser-result-{PHASE}.json', {'status': 'PASS', 'stage': STAGE,
         'checks': len(CHECKS), 'browser_closed': True, 'no_secrets_recorded': True})


try:
    run()
except BaseException as error:
    # Avoid exception dumps containing request URLs, cookies or response bodies.
    save(f'browser-result-{PHASE}.json', {'status': 'FAIL', 'stage': STAGE,
         'error_type': type(error).__name__, 'completed_checks': len(CHECKS)})
    print('Browser validation failed in stage:', STAGE, 'type:', type(error).__name__)
    sys.exit(1)
