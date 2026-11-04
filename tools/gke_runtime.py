"""Exclusive, bounded HISJB runtime. Never operates on another project/context."""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4
from resume_tfi_cloud import ROOT, PROJECT, ACCOUNT, SDK, TF, ENV, token_env, assert_billing

RUNTIME = ROOT / 'infrastructure/opentofu/runtime'
PRIVATE = ROOT / '.runtime/gke-runtime-20261104'
OUT = ROOT / 'evidence/phase4/gke-runtime-20261104'
KUBECTL = Path('C:/Program Files/Docker/Docker/resources/bin/kubectl.exe')
HELM = ROOT.parent / 'trazacat-pow/.tools/helm-v4.3.1/windows-amd64/helm.exe'
CLUSTER = 'hisjb-tfi-temp'
ZONE = 'us-central1-a'
NAMESPACE = 'tfi-hospital'
PRIVATE.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
KENV = dict(ENV, KUBECONFIG=str(PRIVATE / 'kubeconfig.json'))

def save(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2), encoding='utf-8')

def command(name, cmd, timeout=120, env=KENV, private=False, stdin=None, check=True):
    started = datetime.now(timezone.utc).isoformat()
    # Capture to files while running, so failures cannot erase partial logs.
    dest = PRIVATE if private else OUT
    if (dest / (name + '.stdout.txt')).exists():
        name += '-' + datetime.now(timezone.utc).strftime('%H%M%S%f')
    with (dest / (name + '.stdout.txt')).open('wb') as stdout, (dest / (name + '.stderr.txt')).open('wb') as stderr:
        p = subprocess.run([str(x) for x in cmd], cwd=ROOT, env=env, input=stdin,
            stdout=stdout, stderr=stderr, timeout=timeout)
    with (OUT / 'COMMANDS.jsonl').open('a', encoding='utf-8') as log:
        log.write(json.dumps({'utc': started, 'name': name, 'command': [str(x) for x in cmd],
            'exit_code': p.returncode, 'private_output': private, 'stdin_recorded': False}) + '\n')
    print(json.dumps({'step': name, 'exit_code': p.returncode}), flush=True)
    if check and p.returncode:
        print((dest / (name + '.stderr.txt')).read_text(errors='replace')[:3000], flush=True)
        raise RuntimeError(name + ' failed; no automatic deployment retry')
    return (dest / (name + '.stdout.txt')).read_bytes()

def gc(name, args, **kw):
    return json.loads(command(name, [SDK, *args, '--project=' + PROJECT, '--format=json'], env=ENV, **kw))

def kube(name, args, **kw):
    return command(name, [KUBECTL, '--context=hisjb-tfi-exclusive', '--namespace=' + NAMESPACE, *args], **kw)

def bounded():
    marker = json.loads((PRIVATE / 'runtime-start.json').read_text())
    elapsed = time.time() - marker['epoch']
    if elapsed > 90*60: raise RuntimeError('Experiment deadline reached; cleanup required')
    return elapsed

def plan():
    assert not (PRIVATE / 'runtime-start.json').exists(), 'Runtime already attempted'
    assert_billing()
    audit = ROOT / 'evidence/phase4/gcp-resume-20261104'
    quotas = json.loads((audit / 'gke-consumer-quotas.json').read_text())
    zonal = next(m for m in quotas['metrics'] if m['metric'] == 'container.googleapis.com/clusters_per_zone')
    buckets = zonal['consumerQuotaLimits'][0]['quotaBuckets']
    assert int(next(b for b in buckets if b.get('dimensions', {}).get('zone') == ZONE)['effectiveLimit']) >= 1
    for name in ('gke', 'vm', 'disk', 'ip', 'forwarding'):
        assert json.loads((audit / (name + '-inventory.stdout.txt')).read_text()) == []
    with urllib.request.urlopen('https://api.ipify.org?format=json', timeout=20) as response:
        ip = ipaddress.ip_address(json.load(response)['ip'])
    assert ip.version == 4 and ip.is_global
    (PRIVATE / 'operator.json').write_text(json.dumps({'cidr': str(ip) + '/32'}))
    command('runtime-fmt-check', [TF, '-chdir=' + str(RUNTIME), 'fmt', '-check'])
    command('runtime-validate', [TF, '-chdir=' + str(RUNTIME), 'validate', '-no-color'])
    target = PRIVATE / 'runtime.tfplan'
    command('runtime-plan', [TF, '-chdir=' + str(RUNTIME), 'plan', '-input=false', '-no-color',
        '-out=' + str(target), '-var=project_id=' + PROJECT, '-var=operator_ipv4_cidr=' + str(ip) + '/32'],
        timeout=240, env=token_env())
    data = json.loads(command('runtime-plan-json', [TF, '-chdir=' + str(RUNTIME), 'show', '-json', str(target)], private=True))
    allowed = {'google_compute_network.tfi', 'google_compute_subnetwork.tfi', 'google_service_account.nodes',
        'google_project_iam_member.node_system', 'google_artifact_registry_repository_iam_member.node_reader',
        'google_container_cluster.tfi'}
    changes = data['resource_changes']
    assert {r['address'] for r in changes} == allowed
    for r in changes:
        assert r['change']['actions'] == ['create']
        after = r['change']['after']
        assert after.get('project', PROJECT) == PROJECT
        if r['address'] == 'google_container_cluster.tfi':
            assert after['name'] == CLUSTER and after['location'] == ZONE and after['initial_node_count'] == 1
            node = after['node_config'][0]
            assert node['machine_type'] == 'e2-standard-4' and node['disk_size_gb'] == 30 and node['disk_type'] == 'pd-standard'
    save('runtime-plan-review.json', {'status': 'PASS', 'project': PROJECT, 'account': ACCOUNT,
        'creates': sorted(allowed), 'deletes': 0, 'replacements': 0, 'vm_count': 1, 'machine': 'e2-standard-4',
        'max_seconds': 7200, 'estimated_usd': 0.5901, 'budget_usd': 2,
        'plan_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})

def create():
    marker = PRIVATE / 'runtime-start.json'
    assert not marker.exists(), 'Only one runtime creation attempt allowed'
    review = json.loads((OUT / 'runtime-plan-review.json').read_text())
    assert review['status'] == 'PASS'
    target = PRIVATE / 'runtime.tfplan'
    assert hashlib.sha256(target.read_bytes()).hexdigest() == review['plan_sha256']
    image = json.loads((ROOT / 'evidence/phase4/image-oidc-20261104/IMAGE_VERIFIED.json').read_text())
    assert image['status'] == 'PASS'
    assert_billing()
    env = token_env()
    marker.write_text(json.dumps({'epoch': time.time(), 'utc': datetime.now(timezone.utc).isoformat(),
        'project': PROJECT, 'plan_sha256': review['plan_sha256']}))
    # Independent deadline guard survives an interrupted assistant/tool session.
    with (OUT / 'deadline-guard.log').open('ab') as log:
        guard = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), 'guard'], cwd=ROOT,
            env=ENV, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    save('deadline-guard.json', {'pid': guard.pid, 'cleanup_after_minutes': 90, 'scope': PROJECT})
    try:
        command('runtime-apply', [TF, '-chdir=' + str(RUNTIME), 'apply', '-input=false', '-no-color', '-parallelism=2', str(target)],
            timeout=1500, env=env)
        connect()
    except BaseException:
        cleanup()
        raise

def connect():
    cluster = gc('cluster-actual', ['container', 'clusters', 'describe', CLUSTER, '--zone=' + ZONE])
    assert cluster['name'] == CLUSTER and cluster['status'] == 'RUNNING'
    # Keep short-lived user token out of process arguments and public artifacts.
    token = token_env()['GOOGLE_OAUTH_ACCESS_TOKEN']
    config = {'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'hisjb-tfi-exclusive',
        'clusters': [{'name': CLUSTER, 'cluster': {'server': 'https://' + cluster['endpoint'],
            'certificate-authority-data': cluster['masterAuth']['clusterCaCertificate']}}],
        'users': [{'name': 'isolated-sdk-session', 'user': {'token': token}}],
        'contexts': [{'name': 'hisjb-tfi-exclusive', 'context': {'cluster': CLUSTER,
            'user': 'isolated-sdk-session', 'namespace': NAMESPACE}}]}
    (PRIVATE / 'kubeconfig.json').write_text(json.dumps(config))
    nodes = json.loads(kube('gke-nodes', ['get', 'nodes', '-o', 'json']))
    assert len(nodes['items']) == 1
    assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in nodes['items'][0]['status']['conditions'])
    save('gke-ready.json', {'status': 'PASS', 'project': PROJECT, 'cluster': CLUSTER, 'zone': ZONE,
        'version': cluster['currentMasterVersion'], 'nodes': 1, 'verified_utc': datetime.now(timezone.utc).isoformat()})

def install():
    bounded()
    existing = json.loads(kube('namespace-before', ['get', 'namespaces', '-o', 'json']))
    assert NAMESPACE not in {v['metadata']['name'] for v in existing['items']}
    kube('create-exclusive-namespace', ['create', 'namespace', NAMESPACE])
    credentials = {r: secrets.token_urlsafe(36) for r in ('mesa', 'direccion', 'legal', 'bio', 'auditor', 'operator', 'peer')}
    actors = {'actors': {r: str(uuid4()) for r in ('mesa', 'direccion', 'legal', 'bio')}}
    (PRIVATE / 'credentials.json').write_text(json.dumps(credentials))
    (PRIVATE / 'actors.json').write_text(json.dumps(actors))
    kube('create-ephemeral-secret', ['create', 'secret', 'generic', 'hisjb-credentials',
        '--from-file=credentials.json=' + str(PRIVATE / 'credentials.json')])
    kube('create-synthetic-actors', ['create', 'configmap', 'hisjb-actors', '--from-file=actors.json=' + str(PRIVATE / 'actors.json')])
    kube('storageclass', ['apply', '-f', str(ROOT / 'infrastructure/kubernetes/storageclass.yaml')])
    release(1, 1, 'demo', 'dynamic')

def release(n, d, experiment, mode='fixed'):
    bounded()
    assert n in (1, 3, 5) and d in (1, 2, 3)
    image = json.loads((ROOT / 'evidence/phase4/image-oidc-20261104/IMAGE_VERIFIED.json').read_text())
    command('helm-' + experiment, [HELM, 'upgrade', '--install', 'hisjb', str(ROOT / 'infrastructure/helm/hisjb'),
        '--kube-context=hisjb-tfi-exclusive', '--namespace=' + NAMESPACE, '--set', 'replicas=' + str(n),
        '--set', 'difficulty=' + str(d), '--set', 'difficultyMode=' + mode, '--set', 'experiment=' + experiment,
        '--set', 'image.repository=' + image['repository'], '--set', 'image.digest=' + image['digest'],
        '--wait=false', '--timeout=120s'], timeout=150)
    sts=json.loads(kube('revision-'+experiment,['get','statefulset','hisjb','-o','json']))
    desired=sts['status']['updateRevision']
    pods=json.loads(kube('rollout-before-'+experiment,['get','pods','-l','app=hisjb','-o','json']))['items']
    outdated=[p['metadata']['name'] for p in pods if p['metadata']['labels'].get('controller-revision-hash')!=desired]
    assert all(name in ['hisjb-'+str(i) for i in range(5)] for name in outdated)
    if outdated:
        kube('replace-protocol-profile-'+experiment,['delete','pod',*outdated,'--wait=true','--timeout=45s'],timeout=60)
    kube('wait-profile-'+experiment,['wait','--for=condition=Ready','pod','-l','app=hisjb','--timeout=150s'],timeout=170)
    actual=json.loads(kube('verified-profile-'+experiment,['get','pods','-l','app=hisjb','-o','json']))['items']
    assert len(actual)==n and all(p['metadata']['labels'].get('controller-revision-hash')==desired for p in actual)
    kube('pods-' + experiment, ['get', 'pods', '-o', 'json'])
    kube('pvc-' + experiment, ['get', 'pvc', '-o', 'json'])
    kube('services-' + experiment, ['get', 'services', '-o', 'json'])
    kube('statefulsets-' + experiment, ['get', 'statefulsets', '-o', 'json'])
    if (OUT / 'observability-start.json').exists():
        from gke_observability import targets
        targets(n, experiment)

def probe(name, mode, *args, pod='hisjb-0', timeout=120):
    raw = kube(name, ['exec', '-i', pod, '--', 'python', '-B', '-', mode, *[str(a) for a in args]],
        stdin=(ROOT / 'tools/gke_probe.py').read_bytes(), timeout=timeout)
    result = json.loads(raw)
    save(name + '.json', result)
    return result

def snapshot():
    bounded(); probe('snapshot-demo', 'snapshot')

def forward():
    bounded()
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 19980))
    log = (OUT / 'port-forward.log').open('ab')
    p = subprocess.Popen([str(KUBECTL), '--context=hisjb-tfi-exclusive', '--namespace=' + NAMESPACE,
        'port-forward', '--address=127.0.0.1', 'pod/hisjb-0', '19980:19980'], env=KENV,
        stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    log.close()
    save('port-forward.json', {'pid': p.pid, 'url': 'http://127.0.0.1:19980/console/', 'scope': PROJECT})
    for _ in range(20):
        if p.poll() is not None: raise RuntimeError('Port-forward exited')
        try:
            with urllib.request.urlopen('http://127.0.0.1:19980/healthz', timeout=2) as response:
                health = json.load(response)
            assert health['node_id'] == 'hisjb-0'
            save('forward-health.json', health); return
        except OSError: time.sleep(0.5)
    raise RuntimeError('Port-forward not healthy')

def stop_forward():
    record = OUT / 'port-forward.json'
    if not record.exists(): return
    pid = json.loads(record.read_text())['pid']
    assert type(pid) is int and pid > 0
    script = "$forwardProcess = Get-CimInstance Win32_Process -Filter 'ProcessId = " + str(pid) + "'; if ($forwardProcess) { if ($forwardProcess.Name -ne 'kubectl.exe' -or $forwardProcess.CommandLine -notlike '*--context=hisjb-tfi-exclusive*' -or $forwardProcess.CommandLine -notlike '*port-forward*') { throw 'Process identity mismatch' }; Stop-Process -Id " + str(pid) + " -ErrorAction Stop };"
    command('stop-exclusive-port-forward', ['powershell', '-NoProfile', '-NonInteractive', '-Command', script], timeout=20)
    save('forward-stopped.json', {'pid': pid, 'stopped': True})

def persistence():
    bounded(); stop_forward()
    before = probe('persistence-before', 'snapshot')
    assert len(before['chains'][0]['blocks']) > 1, 'Mine a real block before persistence test'
    pod = json.loads(kube('pod-before-recreation', ['get', 'pod', 'hisjb-0', '-o', 'json']))
    pvc = json.loads(kube('pvc-before-recreation', ['get', 'pvc', 'data-hisjb-0', '-o', 'json']))
    read = "from pathlib import Path; print(Path('/data/demo/state.json').read_text())"
    raw_before = kube('state-before-recreation', ['exec', 'hisjb-0', '--', 'python', '-c', read])
    # The user-requested UI ConfigMap rollout recreates this same pod once.
    release(1, 1, 'demo', 'dynamic')
    kube('wait-hisjb-0', ['wait', '--for=condition=Ready', 'pod/hisjb-0', '--timeout=180s'], timeout=200)
    after = probe('persistence-after', 'snapshot')
    new_pod = json.loads(kube('pod-after-recreation', ['get', 'pod', 'hisjb-0', '-o', 'json']))
    new_pvc = json.loads(kube('pvc-after-recreation', ['get', 'pvc', 'data-hisjb-0', '-o', 'json']))
    raw_after = kube('state-after-recreation', ['exec', 'hisjb-0', '--', 'python', '-c', read])
    assert before['chains'] == after['chains']
    assert [r['body'] for r in before['pending']] == [r['body'] for r in after['pending']]
    assert all(r['http'] == 200 for r in before['pending'] + after['pending'])
    assert raw_before == raw_after and pod['metadata']['uid'] != new_pod['metadata']['uid']
    assert pvc['metadata']['uid'] == new_pvc['metadata']['uid']
    save('PERSISTENCE.json', {'status': 'PASS', 'pvc_uid': pvc['metadata']['uid'],
        'previous_pod_uid': pod['metadata']['uid'], 'new_pod_uid': new_pod['metadata']['uid'],
        'state_sha256_before': hashlib.sha256(raw_before).hexdigest(),
        'state_sha256_after': hashlib.sha256(raw_after).hexdigest(), 'full_chain_and_mempool_equal': True,
        'recreation_reason': 'Authorized console environment ConfigMap rollout; no engine/image change'})

def matrix():
    bounded(); stop_forward()
    assert not (OUT / 'matrix-start.json').exists(), 'No automatic experiment repeat'
    save('matrix-start.json', {'utc': datetime.now(timezone.utc).isoformat()})
    all_results = []
    try:
        for n in (1, 3, 5):
            for d in (1, 2, 3):
                bounded()
                name = f'n{n}-d{d}'
                release(n, d, name)
                for c in (1, 2, 5, 10, 50, 101):
                    bounded()
                    # Ensure a fresh per-role rate window; preserve the original security limits.
                    if c in (50, 101): time.sleep(61)
                    prefix = f'cell-{name}-c{c}'
                    before = [probe(prefix + '-resources-before-' + str(i), 'resources', pod='hisjb-' + str(i)) for i in range(n)]
                    result = probe(prefix, 'cell', c, timeout=180)
                    after = [probe(prefix + '-resources-after-' + str(i), 'resources', pod='hisjb-' + str(i)) for i in range(n)]
                    result['api_cpu_seconds_delta_all_nodes'] = sum(a['api_cpu_seconds'] - b['api_cpu_seconds'] for a,b in zip(after,before))
                    result['api_rss_bytes_all_nodes_after'] = sum(a['api_rss_bytes'] for a in after)
                    result['resource_samples_before'] = before; result['resource_samples_after'] = after
                    save(prefix + '.json', result)
                    all_results.append({'file': prefix + '.json', 'nodes': n, 'difficulty': d,
                        'concurrency': c, 'status': result['status'], 'errors': result['errors']})
                    save('MATRIX_INDEX.json', all_results)
        save('MATRIX_RESULT.json', {'execution': 'COMPLETED', 'cells': len(all_results),
            'all_requests_accepted': all(r['errors'] == 0 for r in all_results)})
    except BaseException as exc:
        save('MATRIX_RESULT.json', {'execution': 'STOPPED', 'completed_cells': len(all_results),
            'error_type': type(exc).__name__, 'reason': str(exc)[:200]})
        raise

def destroy():
    # Destruction is always allowed for this exact newly-created runtime, even after deadline.
    state = RUNTIME / 'terraform.tfstate'
    assert state.exists()
    shutil = __import__('shutil')
    shutil.copy2(state, PRIVATE / 'runtime-before-destroy.tfstate')
    ip = json.loads((PRIVATE / 'operator.json').read_text())['cidr']
    env = token_env()
    target = PRIVATE / 'destroy.tfplan'
    command('destroy-plan', [TF, '-chdir=' + str(RUNTIME), 'plan', '-destroy', '-input=false', '-no-color',
        '-out=' + str(target), '-var=project_id=' + PROJECT, '-var=operator_ipv4_cidr=' + ip], timeout=180, env=env)
    plan_json = json.loads(command('destroy-plan-json', [TF, '-chdir=' + str(RUNTIME), 'show', '-json', str(target)], private=True))
    allowed = set(json.loads((OUT / 'runtime-plan-review.json').read_text())['creates'])
    for change in plan_json.get('resource_changes', []):
        assert change['address'] in allowed and change['change']['actions'] in (['delete'], ['no-op'])
    command('runtime-destroy', [TF, '-chdir=' + str(RUNTIME), 'apply', '-input=false', '-no-color', str(target)], timeout=1500, env=env)
    remaining = {}
    for name, args in [('clusters', ['container', 'clusters', 'list']), ('instances', ['compute', 'instances', 'list']),
        ('disks', ['compute', 'disks', 'list']), ('addresses', ['compute', 'addresses', 'list']),
        ('forwarding-rules', ['compute', 'forwarding-rules', 'list'])]:
        remaining[name] = gc('remaining-' + name, args)
    save('CLEANUP.json', {'utc': datetime.now(timezone.utc).isoformat(), 'remaining': remaining,
        'status': 'PASS' if not any(remaining.values()) else 'PARTIAL', 'scope': 'Only exclusive HISJB runtime'})

def cleanup():
    # Never delete a PVC until its JSON state has been exported and hash-checked.
    stop_forward()
    if (PRIVATE / 'kubeconfig.json').exists():
        connect()
        pods = json.loads(kube('cleanup-pods-before', ['get', 'pods', '-l', 'app=hisjb', '-o', 'json']))['items']
        import base64
        verified_exports=[]
        for pod in pods:
            name = pod['metadata']['name']
            assert name in ['hisjb-' + str(i) for i in range(5)]
            if pod.get('status', {}).get('phase') != 'Running': continue
            exported = json.loads(kube('export-' + name, ['exec', '-i', name, '--', 'python', '-B', '-'],
                stdin=(ROOT / 'tools/gke_export_state.py').read_bytes(), timeout=90))
            for row in exported:
                raw = base64.b64decode(row['base64'])
                assert hashlib.sha256(raw).hexdigest() == row['sha256']
                path = (OUT / 'preserved-state' / name / row['path']).resolve()
                assert path.is_relative_to((OUT / 'preserved-state').resolve())
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
                assert hashlib.sha256(path.read_bytes()).hexdigest()==row['sha256']
                verified_exports.append({'file':path.relative_to(OUT).as_posix(),'bytes':len(raw),
                    'sha256':row['sha256'],'method':row['method']})
            kube('application-log-' + name, ['logs', name, '--timestamps', '--tail=2000'], check=False)
        claims = json.loads(kube('cleanup-pvc-before', ['get', 'pvc', '-o', 'json']))['items']
        if claims:
            assert pods, 'Claims exist but no nodes could be exported; preserve and report'
            running_names={p['metadata']['name'] for p in pods if p.get('status',{}).get('phase')=='Running'}
            assert all(c['metadata']['name'].removeprefix('data-') in running_names for c in claims), 'Every PVC needs its running owner for verified export'
            for claim in claims:
                assert claim['metadata']['name'] in ['data-hisjb-' + str(i) for i in range(5)]
                assert claim['metadata'].get('labels', {}).get('project') == 'hisjb-tfi'
            save('export-verified.json', {'pods': [p['metadata']['name'] for p in pods],
                'claims': [p['metadata']['name'] for p in claims], 'hashes_verified': True,
                'json_parsed_and_sqlite_integrity_checked':True,'files':verified_exports})
            command('helm-uninstall-exclusive', [HELM, 'uninstall', 'hisjb', '--kube-context=hisjb-tfi-exclusive',
                '--namespace=' + NAMESPACE, '--wait', '--timeout=120s'], timeout=150)
            kube('delete-exported-claims', ['delete', 'pvc', *[c['metadata']['name'] for c in claims], '--wait=true', '--timeout=120s'], timeout=150)
    obs_forward=OUT / 'observability-forward.json'
    if obs_forward.exists():
        pid=json.loads(obs_forward.read_text())['pid']
        assert type(pid) is int and pid>0
        script="$p=Get-CimInstance Win32_Process -Filter 'ProcessId = "+str(pid)+"'; if ($p) { if ($p.Name -ne 'kubectl.exe' -or $p.CommandLine -notlike '*hisjb-observability*' -or $p.CommandLine -notlike '*hisjb-tfi-exclusive*') { throw 'Identity mismatch' }; Stop-Process -Id "+str(pid)+" -ErrorAction Stop }"
        command('stop-exclusive-observability-forward',['powershell','-NoProfile','-NonInteractive','-Command',script],timeout=20)
    destroy()
    (PRIVATE / 'runtime-finished.json').write_text(json.dumps({'utc': datetime.now(timezone.utc).isoformat()}))

def guard():
    marker = json.loads((PRIVATE / 'runtime-start.json').read_text())
    while time.time() - marker['epoch'] < 90*60:
        if (PRIVATE / 'runtime-finished.json').exists(): return
        time.sleep(20)
    if not (PRIVATE / 'runtime-finished.json').exists():
        print('Time budget reached: exporting and deleting exclusively HISJB runtime', flush=True)
        cleanup()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['plan', 'create', 'connect', 'install', 'snapshot', 'forward', 'persistence', 'matrix', 'destroy', 'cleanup', 'guard'])
    globals()[parser.parse_args().stage]()
