"""One bounded Docker demonstration on an ephemeral GitHub runner; never GCP.

The browser joins only the container network namespace, so the production
loopback/session/Origin/CSRF checks are exercised without weakening them.
No ports are published. No approved core tests are repeated.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/container-validation'
PRIVATE = ROOT / '.runtime/container-validation'
BASE = 'python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c'
RUN = os.environ.get('GITHUB_RUN_ID', '')
assert re.fullmatch(r'[0-9]+', RUN), 'Only an authorized GitHub runner may execute this tool'
assert os.environ.get('GITHUB_REPOSITORY') == 'silvitagomez572-alt/unlu-tfi-blockchain-hospital'
assert os.environ.get('GITHUB_REF') == 'refs/heads/tfi/despliegue-temporal'
NAME = 'hisjb-validation-' + RUN
LABEL = 'unlu.tfi.run=' + RUN
OUT.mkdir(parents=True, exist_ok=True)


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def command(args, timeout=30, check=True):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f'command failed: {args[0]} {args[1]} (exit {p.returncode})')
    return p


def container_info():
    p = command(['docker', 'inspect', NAME], check=False)
    return json.loads(p.stdout)[0] if p.returncode == 0 else None


def cleanup():
    """Remove only exact run-labelled objects; preserve evidence and data files."""
    item = container_info()
    if item:
        assert item['Config']['Labels'].get('unlu.tfi.run') == RUN
        logs = command(['docker', 'logs', '--timestamps', NAME], check=False)
        (OUT / 'application.log').write_bytes(logs.stdout + logs.stderr)
        command(['docker', 'stop', '--time', '8', NAME], timeout=20)
        final = container_info()
        save('container-final-state.json', final['State'])
        command(['docker', 'rm', NAME])
    net = command(['docker', 'network', 'inspect', NAME], check=False)
    if net.returncode == 0:
        network = json.loads(net.stdout)[0]
        assert network['Labels'].get('unlu.tfi.run') == RUN
        assert not network['Containers'], 'Do not remove a network with live containers'
        command(['docker', 'network', 'rm', NAME])
    # Exact ephemeral secrets, never a recursive delete of state or user data.
    for name in ('credentials.json', 'qr-private.json'):
        target = (PRIVATE / name).resolve()
        assert target.parent == PRIVATE.resolve()
        if target.exists():
            command(['sudo', 'rm', '--', str(target)])
    remaining = command(['docker', 'ps', '-a', '--filter', 'label=' + LABEL, '--format', '{{.ID}}']).stdout.decode().strip()
    networks = command(['docker', 'network', 'ls', '--filter', 'label=' + LABEL, '--format', '{{.ID}}']).stdout.decode().strip()
    assert not remaining and not networks
    save('cleanup.json', {'utc': datetime.now(timezone.utc).isoformat(), 'containers_remaining': [],
                         'networks_remaining': [], 'secrets_removed': True,
                         'scope': 'Only this ephemeral GitHub run; no Windows or GCP resources'})


def seal():
    files = [p for p in OUT.rglob('*') if p.is_file() and p.name != 'MANIFIESTO_SHA256.json']
    assert sum(p.stat().st_size for p in files) <= 20 * 1024**2, 'artifact limit'
    # Compare all emitted text/binaries with the in-memory random role credentials
    # before deleting them in the normal path. Also reject known secret formats.
    for p in files:
        raw = p.read_bytes()
        assert not re.search(rb'(gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)', raw)
    save('MANIFIESTO_SHA256.json', {p.relative_to(OUT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)})


def available_mib():
    return int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))) / 1024


def browser(phase):
    item = container_info()
    assert item and item['State']['Running']
    python = ROOT / '.runtime/browser/bin/python'
    args = ['sudo', '--preserve-env=PLAYWRIGHT_BROWSERS_PATH,PYTHONDONTWRITEBYTECODE',
            'nsenter', '-t', str(item['State']['Pid']), '-n', str(python), '-B',
            str(ROOT / 'tools/container_browser_validation.py'), phase]
    started = time.monotonic()
    with (OUT / f'browser-{phase}.log').open('wb') as log:
        p = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            minimum = available_mib()
            while p.poll() is None:
                minimum = min(minimum, available_mib())
                if minimum < 512 or time.monotonic() - started > 180:
                    raise RuntimeError('browser memory floor / 180 second deadline')
                time.sleep(0.5)
        finally:
            if p.poll() is None:
                command(['sudo', 'kill', '-TERM', '--', '-' + str(p.pid)], check=False)
                p.wait(timeout=10)
        save(f'browser-{phase}-resources.json', {'elapsed_seconds': time.monotonic() - started,
             'runner_available_memory_min_mib': minimum, 'exit_code': p.returncode})
        assert p.returncode == 0, f'browser {phase} failed; no retry'


def run():
    assert not PRIVATE.exists(), 'Single execution only; no implicit retry'
    assert available_mib() >= 2048, 'runner preflight needs 2 GiB'
    approved = json.loads((ROOT / 'evidence/phase2/APPROVED_CORE_SHA256.json').read_text())
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in approved.items())
    save('approved-core-integrity.json', {'status': 'PASS', 'unchanged_files': len(approved),
                                        'tests_reexecuted': False})
    PRIVATE.mkdir(parents=True)
    credentials = {role: secrets.token_urlsafe(32) for role in ('mesa', 'direccion', 'legal', 'bio', 'auditor', 'operator', 'peer')}
    credential_path = PRIVATE / 'credentials.json'
    credential_path.write_text(json.dumps(credentials))
    credential_path.chmod(0o600)
    command(['sudo', 'chown', '10001:10001', str(credential_path)])
    (PRIVATE / 'actors.json').write_text(json.dumps({'actors': {r: str(uuid4()) for r in ('mesa', 'direccion', 'legal', 'bio')}}))
    data = PRIVATE / 'data'
    data.mkdir()
    command(['sudo', 'chown', '10001:10001', str(data)])
    image = 'hisjb-validation:' + RUN
    started = time.monotonic()
    save('environment.json', {'run_id': RUN, 'commit': os.environ['GITHUB_SHA'],
         'utc': datetime.now(timezone.utc).isoformat(), 'base_image': BASE,
         'environment': 'Docker on isolated Ubuntu 24.04 GitHub runner, NOT GKE or local Windows',
         'application_memory_limit_mib': 192, 'browser_deadline_seconds_per_phase': 180,
         'runner_memory_floor_mib': 512, 'browser_preflight_mib': available_mib(),
         'LANG': os.environ.get('LANG'), 'LC_ALL': os.environ.get('LC_ALL'),
         'published_ports': [], 'GCP_calls': False})
    try:
        with (OUT / 'docker-build.log').open('wb') as log:
            p = subprocess.run(['docker', 'build', '--platform', 'linux/amd64', '--build-arg', 'PYTHON_IMAGE=' + BASE,
                 '--label', LABEL, '--tag', image, '.'], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=360)
        assert p.returncode == 0, 'image build failed; no retry'
        info = json.loads(command(['docker', 'image', 'inspect', image]).stdout)[0]
        assert info['Architecture'] == 'amd64' and info['Os'] == 'linux' and info['Config']['User'] == '10001:10001'
        assert info['Size'] <= 500 * 1024**2
        save('image.json', {k: info[k] for k in ('Id', 'Architecture', 'Os', 'Size', 'Created')})
        command(['docker', 'network', 'create', '--label', LABEL, NAME])
        command(['docker', 'run', '-d', '--name', NAME, '--label', LABEL, '--network', NAME,
             '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
             '--pids-limit', '128', '--memory', '192m', '--memory-swap', '192m', '--cpus', '1',
             '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
             '--mount', f'type=bind,source={credential_path},target=/run/hisjb/credentials.json,readonly',
             '--mount', f'type=bind,source={PRIVATE / "actors.json"},target=/config/actors.json,readonly',
             '--mount', f'type=bind,source={data},target=/data',
             '-e', 'POD_NAME=hisjb-0', '-e', 'POD_NAMESPACE=tfi-hospital', '-e', 'TFI_REPLICAS=1',
             '-e', 'TFI_EXPERIMENT=demo', '-e', 'TFI_DIFFICULTY=1', image])
        browser('before')
        ip = container_info()['NetworkSettings']['Networks'][NAME]['IPAddress']
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            opener.open(urllib.request.Request('http://' + ip + ':19980/console/', headers={'Host': '127.0.0.1:19980'}), timeout=3)
            raise AssertionError('console unexpectedly accessible over Docker bridge')
        except urllib.error.HTTPError as error:
            assert error.code == 403
        save('bridge-isolation.json', {'status': 'PASS', 'http': 403,
             'test': 'Console denies Docker bridge client even with loopback Host header'})
        (OUT / 'docker-stats-before.txt').write_bytes(command(['docker', 'stats', '--no-stream', '--format', '{{json .}}', NAME]).stdout)
        state_before = command(['sudo', 'cat', str(data / 'demo/state.json')]).stdout
        (OUT / 'state-before.json').write_bytes(state_before)
        # Stop/start only our newly-created container, retaining the same bind mount.
        command(['docker', 'stop', '--time', '8', NAME], timeout=20)
        command(['docker', 'start', NAME])
        browser('after')
        state_after = command(['sudo', 'cat', str(data / 'demo/state.json')]).stdout
        (OUT / 'state-after.json').write_bytes(state_after)
        assert state_before == state_after, 'persisted chain+mempool snapshot changed unexpectedly'
        save('persistence.json', {'status': 'PASS', 'byte_identical': True,
             'before_sha256': hashlib.sha256(state_before).hexdigest(), 'after_sha256': hashlib.sha256(state_after).hexdigest(),
             'method': 'Exact same retained bind directory across docker stop/start; no PVC or GKE'})
        (OUT / 'docker-stats-after.txt').write_bytes(command(['docker', 'stats', '--no-stream', '--format', '{{json .}}', NAME]).stdout)
        save('result.json', {'status': 'PASS', 'elapsed_seconds': time.monotonic() - started,
             'scope': 'One-node Docker and genuine browser application demonstration; no distributed/GKE claim'})
    except BaseException as exc:
        save('result.json', {'status': 'FAIL', 'error_type': type(exc).__name__,
                            'elapsed_seconds': time.monotonic() - started, 'automatic_retry': False})
        raise
    finally:
        # Logs contain no access log URLs, cookies or request bodies.
        cleanup()
        for f in OUT.rglob('*'):
            if f.is_file():
                raw = f.read_bytes()
                assert not any(secret.encode() in raw for secret in credentials.values()), 'credential in artifact'
        seal()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cleanup-and-seal', action='store_true')
    options = parser.parse_args()
    if options.cleanup_and_seal:
        cleanup()
        seal()
    else:
        run()
