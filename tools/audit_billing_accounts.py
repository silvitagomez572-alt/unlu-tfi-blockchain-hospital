"""Read-only post-payment audit. No billing assignments or resource creation."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT.parent / 'unlu-tp3/tools/google-cloud-sdk/bin/gcloud.cmd'
CONFIG = ROOT / '.runtime/gcloud-tfi-payment-audit-20261104'
OUT = ROOT / 'evidence/phase4/billing-payment-audit-20261104'
PROJECT = 'unlu-tfi-hisjb-20261104'
ACCOUNTS = ('01091D-82ABD9-7BDBC4', '010351-FEA1D7-2CCE98')
ENV = dict(os.environ, CLOUDSDK_CONFIG=str(CONFIG), CLOUDSDK_PYTHON=sys.executable,
           CLOUDSDK_CORE_DISABLE_USAGE_REPORTING='true', CLOUDSDK_CORE_DISABLE_PROMPTS='1')
OUT.mkdir(parents=True, exist_ok=True)


def cli(name, args):
    p = subprocess.run([str(SDK), *args], env=ENV, capture_output=True, timeout=90)
    (OUT / (name + '.stdout.txt')).write_bytes(p.stdout)
    (OUT / (name + '.stderr.txt')).write_bytes(p.stderr)
    with (OUT / 'COMMANDS.jsonl').open('a') as f:
        f.write(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'command': ['gcloud', *args], 'exit_code': p.returncode}) + '\n')
    print(json.dumps({'query': name, 'exit_code': p.returncode}), flush=True)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else None


def test_permissions(token, name, url, permissions):
    # POST testIamPermissions is a read-only permission check, not setIamPolicy.
    req = urllib.request.Request(url, data=json.dumps({'permissions': permissions}).encode(),
         headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            status, result = response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        status, result = exc.code, json.loads(exc.read())
    (OUT / (name + '.json')).write_text(json.dumps({'http': status, 'result': result}, indent=2))
    with (OUT / 'COMMANDS.jsonl').open('a') as f:
        f.write(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'method': 'POST testIamPermissions (read-only)', 'url': url, 'permissions': permissions, 'http': status}) + '\n')
    return result


def audit():
    active = cli('auth', ['auth', 'list', '--filter=status:ACTIVE', '--format=json'])
    if not active:
        print('AUTHENTICATION_REQUIRED', flush=True)
        return 2
    assert len(active) == 1 and active[0]['account'] == 'silvitagomez572@gmail.com'
    p = subprocess.run([str(SDK), 'auth', 'print-access-token'], env=ENV, capture_output=True, timeout=60)
    assert p.returncode == 0
    token = p.stdout.decode().strip()
    results = {}
    for account in ACCOUNTS:
        results[account] = {'account': cli(account + '-account', ['billing', 'accounts', 'describe', account, '--format=json']),
            'projects': cli(account + '-projects', ['billing', 'projects', 'list', '--billing-account=' + account, '--format=json']),
            'permissions': test_permissions(token, account + '-permissions',
                'https://cloudbilling.googleapis.com/v1/billingAccounts/' + account + ':testIamPermissions',
                ['billing.accounts.get', 'billing.accounts.getPaymentInfo', 'billing.accounts.getSpendingInformation',
                 'billing.resourceAssociations.list', 'billing.resourceAssociations.create'])}
    results['project'] = cli('project', ['projects', 'describe', PROJECT, '--format=json'])
    results['project_billing'] = cli('project-billing', ['billing', 'projects', 'describe', PROJECT, '--format=json'])
    results['project_permissions'] = test_permissions(token, 'project-permissions',
        'https://cloudresourcemanager.googleapis.com/v1/projects/' + PROJECT + ':testIamPermissions',
        ['resourcemanager.projects.get', 'resourcemanager.projects.createBillingAssignment',
         'serviceusage.services.get', 'serviceusage.quotas.get'])
    results['enabled_services'] = cli('enabled-services', ['services', 'list', '--enabled', '--project=' + PROJECT, '--format=json'])
    results['quota_status'] = 'Not confirmed: the public BillingAccount resource exposes no numeric project-linking quota or payment balance.'
    results['read_only'] = True
    results['original_account_remains_only_authorized_assignment'] = ACCOUNTS[0]
    (OUT / 'SDK_RESULTS.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results), flush=True)
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['login', 'read', 'revoke'])
    args = parser.parse_args()
    if args.stage == 'login':
        CONFIG.mkdir(parents=True, exist_ok=True)
        # Official interactive consent: completed personally, never via automation.
        result = subprocess.run([str(SDK), 'auth', 'login', 'silvitagomez572@gmail.com'], env=ENV)
        sys.exit(result.returncode)
    elif args.stage == 'read':
        sys.exit(audit())
    else:
        cli('isolated-session-revoke', ['auth', 'revoke', 'silvitagomez572@gmail.com', '--quiet'])
        assert not cli('isolated-session-after-revoke', ['auth', 'list', '--format=json'])
