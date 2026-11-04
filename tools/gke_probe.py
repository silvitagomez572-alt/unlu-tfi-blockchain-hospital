"""Run through kubectl exec stdin inside a HISJB pod. No credential is emitted."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from uuid import uuid4
import httpx
from blockchain.block import Block
from blockchain.validation import validate_chain
from deployment.cluster import settings_from_environment

MODE = sys.argv[1]
N = int(os.environ['TFI_REPLICAS'])
CREDS = json.loads(Path('/run/hisjb/credentials.json').read_text())
SETTINGS = settings_from_environment(os.environ, json.loads(Path('/config/actors.json').read_text()))
BASES = ['http://hisjb-' + str(i) + '.hisjb-headless.tfi-hospital.svc.cluster.local:19980' for i in range(N)]
CONFIG = SETTINGS.config()

def usage():
    fields = Path('/proc/1/stat').read_text().rsplit(')', 1)[1].split()
    rss = next(line.split()[1] for line in Path('/proc/1/status').read_text().splitlines() if line.startswith('VmRSS:'))
    return {'api_cpu_seconds': (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'),
        'api_rss_bytes': int(rss) * 1024, 'source': '/proc/1/stat and /proc/1/status (API process only)',
        'monotonic': time.perf_counter()}

async def main():
    async with httpx.AsyncClient(timeout=12, trust_env=False, limits=httpx.Limits(max_connections=120, max_keepalive_connections=12)) as client:
        async def req(i, method, path, role='auditor', data=None):
            headers = {} if role is None else {'Authorization': 'Bearer ' + CREDS[role]}
            started = time.perf_counter()
            try:
                r = await client.request(method, BASES[i] + path, headers=headers, json=data)
                body = r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text
                return {'http': r.status_code, 'seconds': time.perf_counter() - started, 'body': body}
            except httpx.HTTPError as exc:
                return {'http': None, 'seconds': time.perf_counter() - started, 'error_type': type(exc).__name__}

        async def chains():
            rows = [await req(i, 'GET', '/chain', 'peer') for i in range(N)]
            for row in rows:
                assert row['http'] == 200, 'Chain unavailable'
                blocks = tuple(Block.from_dict(b, max_transactions=CONFIG.max_transactions_per_block) for b in row['body']['blocks'])
                result = validate_chain(blocks, CONFIG)
                assert result.valid, 'Full protocol validation rejected chain'
                assert row['body']['cumulative_work'] == result.cumulative_work
            return [r['body'] for r in rows]

        if MODE == 'snapshot':
            result = {'utc': datetime.now(timezone.utc).isoformat(), 'chains': await chains(),
                'pending': [await req(i, 'GET', '/transactions/pending', 'peer') for i in range(N)],
                'peers': [await req(i, 'GET', '/peers', 'auditor') for i in range(N)],
                'metrics': [await req(i, 'GET', '/metrics', None) for i in range(N)], 'usage': usage()}
        elif MODE == 'resources':
            result = usage()
        elif MODE == 'cell':
            concurrency = int(sys.argv[2]); assert concurrency in (1, 2, 5, 10, 50, 101)
            # Final closure order: keep previous stress evidence; submit no new stress.
            if concurrency > 10:
                raise RuntimeError('Optional stress disabled by final closure order; no requests submitted')
            initial = await chains()
            assert all(c['blocks'] == initial[0]['blocks'] for c in initial), 'Cell starts from divergent chains'
            pending_before=[await req(i,'GET','/transactions/pending','peer') for i in range(N)]
            usage_before = usage()
            correlation = str(uuid4())
            payloads = [{'document_id': str(uuid4()), 'version_id': str(uuid4()), 'fixture_id': 1 + i,
                'metadata': {'schema': 'synthetic-circuit-v1', 'synthetic': True}} for i in range(concurrency)]
            started = time.perf_counter()
            # One unique request per concurrency slot; real HTTP requests to N independent APIs.
            replies = await asyncio.gather(*(req(i % N, 'POST', '/documents/register', 'mesa', p) for i, p in enumerate(payloads)))
            request_window = time.perf_counter() - started
            accepted = [r for r in replies if r['http'] == 202]
            expected = {r['body']['transaction_id'] for r in accepted}
            propagation = None
            propagation_start = time.perf_counter()
            while expected:
                pending = [await req(i, 'GET', '/transactions/pending', 'peer') for i in range(N)]
                if all(r['http'] == 200 and expected <= {t['tx_id'] for t in r['body']} for r in pending):
                    propagation = time.perf_counter() - propagation_start
                    break
                if time.perf_counter() - propagation_start > 20: raise RuntimeError('Mempool propagation did not converge')
                await asyncio.sleep(0.2)
            mined = await req(0, 'POST', '/mine', 'operator') if expected else None
            if mined:
                assert mined['http'] == 200, 'Mining failed'
                assert expected <= {t['tx_id'] for t in mined['body']['block']['transactions']}, 'Accepted transaction missing from mined block'
            sync_start = time.perf_counter()
            sync_replies = [await req(i, 'POST', '/peers/sync', 'operator') for i in range(N)]
            while True:
                final = await chains()
                if all(c['blocks'] == final[0]['blocks'] for c in final): break
                if time.perf_counter() - sync_start > 25: raise RuntimeError('Complete chains did not converge')
                await asyncio.sleep(0.2)
            usage_after = usage()
            pending_after=[await req(i,'GET','/transactions/pending','peer') for i in range(N)]
            lats = sorted(r['seconds'] for r in replies)
            result = {'status': 'PASS' if len(accepted) == concurrency else 'PARTIAL',
                'utc': datetime.now(timezone.utc).isoformat(), 'correlation_id': correlation,
                'nodes': N, 'apis_receiving': N, 'miners_available': N, 'miners_activated': 1,
                'mining_mode': 'one producer, other blockchain nodes validate and synchronize; no competing miners',
                'difficulty': CONFIG.initial_difficulty, 'difficulty_mode': 'fixed', 'concurrency': concurrency,
                'requests': replies, 'accepted': len(accepted), 'errors': concurrency - len(accepted),
                'requested_document_ids':[p['document_id'] for p in payloads],
                'pending_before':pending_before,'pending_after':pending_after,
                'request_window_seconds': request_window, 'throughput_accepted_per_second': len(accepted) / request_window,
                'latency_mean_seconds': statistics.mean(lats), 'latency_p95_seconds': lats[math.ceil(0.95 * len(lats)) - 1],
                'p95_method': 'nearest rank, measured HTTP samples', 'mined': mined,
                'hash_rate_attempts_per_second': mined['body']['attempts'] / mined['body']['elapsed_seconds'] if mined and mined['body']['elapsed_seconds'] > 0 else None,
                'propagation_observed_seconds': propagation, 'sync_observed_seconds': time.perf_counter() - sync_start,
                'sync_replies': sync_replies, 'full_chains_equal': True, 'final_chains': final,
                'usage_before_node0': usage_before, 'usage_after_node0': usage_after,
                'node0_api_cpu_seconds_delta': usage_after['api_cpu_seconds'] - usage_before['api_cpu_seconds'],
                'limitations': ['one sample per concurrency slot', 'one GKE VM shared by all nodes',
                    'client runs inside pod zero; resource observations distinguish PID 1 from the client',
                    'propagation polling resolution 0.2 seconds; no claim of independent worker benchmark']}
        else:
            raise ValueError('Unsupported probe')
        encoded = json.dumps(result)
        assert all(value not in encoded for value in CREDS.values())
        print(encoded)

asyncio.run(main())
