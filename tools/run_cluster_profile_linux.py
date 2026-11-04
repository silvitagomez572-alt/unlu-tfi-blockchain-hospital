"""One NEW integration-boundary test. Does not repeat the approved core/A/B suites."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from run_consensus_linux import memory, members, finish_group

root = Path(__file__).resolve().parents[1]
out = root / 'evidence/deployment-preflight'
out.mkdir(parents=True, exist_ok=True)
assert sys.platform == 'linux'
approved = json.loads((root / 'evidence/phase2/APPROVED_CORE_SHA256.json').read_text())
assert all(hashlib.sha256((root / p).read_bytes()).hexdigest() == h for p, h in approved.items())
case = 'tests/unit/test_cluster_profile.py::test_cluster_isolation_and_configuration'
result = {'utc': datetime.now(timezone.utc).isoformat(), 'case': case, 'status': 'BLOCKED',
          'preflight': memory(), 'timeout_seconds': 12, 'rss_limit_mib': 192,
          'minimum_available_mib': 1024, 'stop_below_mib': 384, 'samples': []}
proc = None
try:
    if result['preflight']['available_bytes'] < 1024**3:
        raise RuntimeError('preflight below 1 GiB; no pytest started')
    cmd = [sys.executable, '-B', 'tools/phase2_pytest_entry.py', case, '-q',
           '-p', 'no:cacheprovider', '--junitxml=' + str(out / 'junit.xml'),
           '--basetemp=' + str(root / '.runtime/cluster-profile-test')]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', PYTHONPATH=str(root))
    with (out / 'test.log').open('wb') as log:
        start = time.monotonic()
        proc = subprocess.Popen(cmd, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        result['pid'] = proc.pid
        while proc.poll() is None:
            current, available = members(proc.pid), memory()['available_bytes']
            elapsed = time.monotonic() - start
            result['samples'].append({'elapsed': elapsed, 'available_bytes': available, 'processes': current})
            if elapsed > 12 or available < 384*1024**2 or any(p['rss_bytes'] > 192*1024**2 for p in current):
                raise RuntimeError('bounded supervisor resource/time limit reached')
            time.sleep(0.05)
        result.update(duration_seconds=time.monotonic()-start, exit_code=proc.returncode,
                      status='PASS' if proc.returncode == 0 else 'FAIL')
except Exception as exc:
    result['reason'] = str(exc)
finally:
    if proc is not None:
        result['active_after_cleanup'] = finish_group(proc)
    (out / 'test-result.json').write_text(json.dumps(result, indent=2))
print(json.dumps({k:v for k,v in result.items() if k != 'samples'}))
raise SystemExit(0 if result['status'] == 'PASS' else 1)
