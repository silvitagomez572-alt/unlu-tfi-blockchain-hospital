"""Bounded continuation after the expressly authorized second-account association."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
from audit_billing_accounts import ROOT, SDK, ENV, PROJECT

ACCOUNT = '010351-FEA1D7-2CCE98'
TF = ROOT.parent / 'unlu-tp2/tools/terraform.exe'
OUT = ROOT / 'evidence/phase4/gcp-resume-20261104'
PRIVATE = ROOT / '.runtime/gcp-resume-20261104'
BOOT = ROOT / 'infrastructure/opentofu/bootstrap'
OUT.mkdir(parents=True, exist_ok=True)
PRIVATE.mkdir(parents=True, exist_ok=True)

def command(name, cmd, timeout=120, env=ENV, private=False):
    start = datetime.now(timezone.utc).isoformat()
    p = subprocess.run([str(x) for x in cmd], env=env, cwd=ROOT, capture_output=True, timeout=timeout)
    dest = PRIVATE if private else OUT
    (dest / (name + '.stdout.txt')).write_bytes(p.stdout)
    (dest / (name + '.stderr.txt')).write_bytes(p.stderr)
    with (OUT / 'COMMANDS.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps({'utc': start, 'name': name, 'command': [str(x) for x in cmd],
            'exit_code': p.returncode, 'private_output': private}) + '\n')
    print(json.dumps({'operation': name, 'exit_code': p.returncode}), flush=True)
    if p.returncode:
        print(p.stderr.decode('utf-8', errors='replace')[:5000], flush=True)
        raise RuntimeError(name + ': stopped; no automatic retry')
    return p.stdout

def gc(name, args, **kw):
    return json.loads(command(name, [SDK, *args, '--format=json'], **kw))

def token_env():
    p = subprocess.run([str(SDK), 'auth', 'print-access-token'], env=ENV, capture_output=True, timeout=60)
    if p.returncode: raise RuntimeError('Isolated SDK authentication unavailable')
    return dict(ENV, GOOGLE_OAUTH_ACCESS_TOKEN=p.stdout.decode().strip(), TF_IN_AUTOMATION='1', CHECKPOINT_DISABLE='1')

def assert_billing():
    billing = gc('billing-enabled', ['billing', 'projects', 'describe', PROJECT])
    assert billing['billingEnabled'] and billing['billingAccountName'] == 'billingAccounts/' + ACCOUNT
    return billing

def plan():
    assert_billing()
    actual = gc('project-identity', ['projects', 'describe', PROJECT])
    assert actual['projectNumber'] == '919344821395' and actual['lifecycleState'] == 'ACTIVE'
    state_path = BOOT / 'terraform.tfstate'
    state = json.loads(state_path.read_text())
    resources = state['resources']
    assert len(resources) == 1 and resources[0]['type'] == 'google_project'
    instance = resources[0]['instances'][0]
    assert instance['attributes']['project_id'] == PROJECT
    backup = PRIVATE / 'bootstrap-before-reconciliation.tfstate'
    if not backup.exists(): shutil.copy2(state_path, backup)
    if instance.get('status') == 'tainted':
        command('untaint-local-project-state', [TF, '-chdir=' + str(BOOT), 'untaint', 'google_project.tfi'])
    command('terraform-fmt-check', [TF, '-chdir=' + str(BOOT), 'fmt', '-check'])
    command('terraform-validate', [TF, '-chdir=' + str(BOOT), 'validate', '-no-color'])
    target = PRIVATE / 'bootstrap.tfplan'
    command('bootstrap-plan', [TF, '-chdir=' + str(BOOT), 'plan', '-input=false', '-no-color', '-parallelism=2',
        '-out=' + str(target), '-var=project_id=' + PROJECT, '-var=billing_account=' + ACCOUNT,
        '-var=github_repository_id=1444937330', '-var=approved_budget_usd=2'], timeout=240, env=token_env())
    raw = command('bootstrap-plan-json', [TF, '-chdir=' + str(BOOT), 'show', '-json', str(target)], private=True)
    data = json.loads(raw)
    changes = []
    for r in data.get('resource_changes', []):
        actions = r['change']['actions']
        assert actions in (['create'], ['no-op']), (r['address'], actions)
        after = r['change'].get('after') or {}
        if after.get('project'): assert after['project'] == PROJECT
        if after.get('billing_account'): assert after['billing_account'] == ACCOUNT
        assert r['type'] != 'google_container_cluster'
        changes.append({'address': r['address'], 'actions': actions})
    review = {'project': PROJECT, 'billing_account': ACCOUNT, 'plan_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
        'no_deletes_or_replacements': True, 'gke_included': False, 'changes': changes}
    (OUT / 'bootstrap-plan-review.json').write_text(json.dumps(review, indent=2))
    print(json.dumps(review), flush=True)

def bootstrap():
    marker = PRIVATE / 'bootstrap-attempt.json'
    if marker.exists(): raise RuntimeError('Bootstrap already attempted; no automatic retry')
    review = json.loads((OUT / 'bootstrap-plan-review.json').read_text())
    target = PRIVATE / 'bootstrap.tfplan'
    assert review['plan_sha256'] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert review['no_deletes_or_replacements'] and not review['gke_included']
    assert_billing()
    env = token_env()
    marker.write_text(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'plan_sha256': review['plan_sha256']}))
    command('bootstrap-apply', [TF, '-chdir=' + str(BOOT), 'apply', '-input=false', '-no-color', '-parallelism=2', str(target)], timeout=600, env=env)
    command('bootstrap-outputs', [TF, '-chdir=' + str(BOOT), 'output', '-json'])

def quotas():
    assert_billing()
    for name, args in [
        ('apis-enabled', ['services', 'list', '--enabled', '--project=' + PROJECT]),
        ('regional-quotas', ['compute', 'regions', 'describe', 'us-central1', '--project=' + PROJECT]),
        ('project-quotas', ['compute', 'project-info', 'describe', '--project=' + PROJECT]),
        ('gke-config', ['container', 'get-server-config', '--zone=us-central1-a', '--project=' + PROJECT]),
        ('gke-inventory', ['container', 'clusters', 'list', '--project=' + PROJECT]),
        ('vm-inventory', ['compute', 'instances', 'list', '--project=' + PROJECT]),
        ('disk-inventory', ['compute', 'disks', 'list', '--project=' + PROJECT]),
        ('ip-inventory', ['compute', 'addresses', 'list', '--project=' + PROJECT]),
        ('forwarding-inventory', ['compute', 'forwarding-rules', 'list', '--project=' + PROJECT])]:
        gc(name, args)

def budget_repair():
    marker = PRIVATE / 'budget-quota-project-correction-attempt.json'
    assert not marker.exists(), 'Corrected budget was already attempted; stop'
    assert_billing()
    shutil.copy2(BOOT / 'terraform.tfstate', PRIVATE / 'bootstrap-before-budget-repair.tfstate')
    command('budget-fmt-check', [TF, '-chdir=' + str(BOOT), 'fmt', '-check'])
    command('budget-validate', [TF, '-chdir=' + str(BOOT), 'validate', '-no-color'])
    target = PRIVATE / 'budget-only.tfplan'
    env = token_env()
    command('budget-corrected-plan', [TF, '-chdir=' + str(BOOT), 'plan', '-input=false', '-no-color',
        '-out=' + str(target), '-var=project_id=' + PROJECT, '-var=billing_account=' + ACCOUNT,
        '-var=github_repository_id=1444937330', '-var=approved_budget_usd=2'], timeout=240, env=env)
    raw = command('budget-plan-json', [TF, '-chdir=' + str(BOOT), 'show', '-json', str(target)], private=True)
    changes = [(r['address'], r['change']['actions']) for r in json.loads(raw).get('resource_changes', [])
        if r['change']['actions'] != ['no-op']]
    assert changes == [('google_billing_budget.tfi', ['create'])], changes
    marker.write_text(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'changes': changes,
        'plan_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}))
    command('budget-corrected-apply', [TF, '-chdir=' + str(BOOT), 'apply', '-input=false', '-no-color', str(target)], timeout=180, env=env)
    command('bootstrap-outputs', [TF, '-chdir=' + str(BOOT), 'output', '-json'])

def gke_preflight():
    assert_billing()
    token = token_env()['GOOGLE_OAUTH_ACCESS_TOKEN']
    def request(name, url, body=None):
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
            headers={'Authorization': 'Bearer ' + token, 'X-Goog-User-Project': PROJECT, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=40) as r: data = json.load(r)
        (OUT / (name + '.json')).write_text(json.dumps(data, indent=2))
        return data
    quotas = request('gke-consumer-quotas',
        'https://serviceusage.googleapis.com/v1beta1/projects/919344821395/services/container.googleapis.com/consumerQuotaMetrics?view=FULL&pageSize=100')
    assert not quotas.get('nextPageToken'), 'Quota result needs further page'
    permissions = ['container.clusters.create', 'container.clusters.delete', 'container.clusters.get',
        'container.clusters.update', 'container.clusters.getCredentials', 'compute.networks.create',
        'compute.networks.delete', 'compute.subnetworks.create', 'compute.subnetworks.delete',
        'iam.serviceAccounts.create', 'iam.serviceAccounts.actAs', 'resourcemanager.projects.setIamPolicy',
        'serviceusage.services.use']
    actual = request('runtime-effective-permissions',
        'https://cloudresourcemanager.googleapis.com/v1/projects/' + PROJECT + ':testIamPermissions', {'permissions': permissions})
    assert set(actual.get('permissions', [])) == set(permissions), 'Required permissions missing'
    regional = json.loads((OUT / 'regional-quotas.stdout.txt').read_text())
    regional = {q['metric']: q for q in regional['quotas']}
    required = {'CPUS': 4, 'E2_CPUS': 4, 'DISKS_TOTAL_GB': 80, 'IN_USE_ADDRESSES': 1, 'INSTANCES': 1}
    for metric, amount in required.items():
        assert regional[metric]['limit'] - regional[metric]['usage'] >= amount, metric
    global_q = json.loads((OUT / 'project-quotas.stdout.txt').read_text())
    global_q = {q['metric']: q for q in global_q['quotas']}
    assert global_q['CPUS_ALL_REGIONS']['limit'] - global_q['CPUS_ALL_REGIONS']['usage'] >= 4
    for name in ['gke-inventory', 'vm-inventory', 'disk-inventory', 'ip-inventory', 'forwarding-inventory']:
        assert json.loads((OUT / (name + '.stdout.txt')).read_text()) == [], name
    relevant = [q for q in quotas.get('metrics', []) if 'cluster' in q.get('metric', '').lower()]
    result = {'compute_required': required, 'permissions_verified': len(permissions),
        'cluster_quota_metrics': relevant, 'empty_runtime_inventory': True, 'billing_account': ACCOUNT,
        'compute_quota_status': 'PASS', 'gke_quota_review_required': True}
    (OUT / 'runtime-preflight.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)

def image_verify():
    repository = 'us-central1-docker.pkg.dev/' + PROJECT + '/hisjb-tfi/hisjb'
    tag = '681343963bb0315f68ddd1e49855e1a8460eeb25'
    image = gc('published-image', ['artifacts', 'docker', 'images', 'describe', repository + ':' + tag, '--project=' + PROJECT])
    digest = image['image_summary']['digest']
    import re
    assert re.fullmatch('sha256:[a-f0-9]{64}', digest)
    result = {'status': 'PASS', 'repository': repository, 'tag': tag, 'digest': digest,
        'source_commit': tag, 'workflow_run': 41886329974, 'verified_utc': datetime.now(timezone.utc).isoformat()}
    (ROOT / 'evidence/phase4/image-oidc-20261104/IMAGE_VERIFIED.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('stage', choices=['plan', 'bootstrap', 'quotas', 'budget-repair', 'gke-preflight', 'image-verify'])
    stage = p.parse_args().stage
    globals()[stage.replace('-', '_')]()
