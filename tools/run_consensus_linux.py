"""Prepared Linux-only supervisor; one real-network scenario, never a whole suite.

No containers or cloud SDK. Memory enforcement is sampled, not a cgroup hard cap.
Only the new child process group is terminated, including on timeout/cancellation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
MiB=1024**2
CAP=192*MiB
MINIMUM=1024*MiB
FLOOR=384*MiB
TIMEOUT=90
CASES={'A':'test_scenario_a_shorter_chain_with_more_work',
       'B':'test_scenario_b_equal_work_reversed_arrival'}

def memory():
    fields={line.split(':',1)[0]:int(line.split()[1])*1024
            for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line}
    return {'total_bytes':fields['MemTotal'],'available_bytes':fields['MemAvailable']}

def process_memory(pid):
    try:
        fields={line.split(':',1)[0]:line.split(':',1)[1].strip()
                for line in Path(f'/proc/{pid}/status').read_text().splitlines()}
        if fields['State'].startswith('Z'): return None
        private=0
        for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
            if line.split(':',1)[0] in ('Private_Clean','Private_Dirty','Private_Hugetlb'):
                private+=int(line.split()[1])*1024
        return {'pid':pid,'rss_bytes':int(fields.get('VmRSS','0 kB').split()[0])*1024,
                'peak_rss_bytes':int(fields.get('VmHWM','0 kB').split()[0])*1024,
                'private_bytes':private}
    except (FileNotFoundError,ProcessLookupError):
        return None

def members(group):
    found=[]
    for path in Path('/proc').iterdir():
        if not path.name.isdigit(): continue
        try:
            if os.getpgid(int(path.name))==group:
                sample=process_memory(int(path.name))
                if sample: found.append(sample)
        except ProcessLookupError:
            pass
    return found

def finish_group(proc):
    # The group was created by Popen(start_new_session=True), not inherited.
    for sig in (signal.SIGTERM,signal.SIGKILL):
        if not members(proc.pid): break
        try: os.killpg(proc.pid,sig)
        except ProcessLookupError: pass
        deadline=time.monotonic()+2
        while members(proc.pid) and time.monotonic()<deadline: time.sleep(0.05)
    proc.wait(timeout=3)
    return members(proc.pid)

def cancelled(signum,frame):
    raise RuntimeError(f'supervisor cancellation signal {signum}')

def main(scenario):
    if sys.platform!='linux': raise SystemExit('Linux only; no local Windows test started')
    out=ROOT/'evidence/consensus-ci'/scenario
    out.mkdir(parents=True,exist_ok=False)
    tmp=ROOT/'.runtime/consensus-ci-data'/scenario
    tmp.parent.mkdir(parents=True,exist_ok=True)
    nodeid='tests/integration/test_phase2_network.py::'+CASES[scenario]
    result={'scenario':scenario,'nodeid':nodeid,'status':'BLOCKED',
            'utc':datetime.now(timezone.utc).isoformat(),'preflight':memory(),
            'start_minimum_bytes':MINIMUM,'stop_below_bytes':FLOOR,
            'cap_per_process_bytes':CAP,'timeout_seconds':TIMEOUT,
            'guard':'RSS/private bytes sampled every 50 ms; not a hard cgroup memory limit',
            'samples':[],'nodes_started':False,'active_after_cleanup':[]}
    proc=None
    started=time.monotonic()
    signal.signal(signal.SIGTERM,cancelled)
    signal.signal(signal.SIGINT,cancelled)
    try:
        expected=json.loads((ROOT/'evidence/phase2/APPROVED_CORE_SHA256.json').read_text())
        result['core_mismatches']=[name for name,digest in expected.items()
                                 if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
        if result['core_mismatches']:
            result['reason']='Approved engine differs; no child started'
        elif result['preflight']['available_bytes']<MINIMUM:
            result['reason']='Less than 1 GiB MemAvailable; no child started'
        else:
            env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONDONTWRITEBYTECODE='1',
                     PYTHONPATH=str(ROOT),TFI_EVIDENCE_DIR=str(out),TFI_INTEGRATION='1')
            cmd=[sys.executable,'-B',str(ROOT/'tools/phase2_pytest_entry.py'),nodeid,'-q','-s',
                 '-p','no:cacheprovider','--junitxml='+str(out/'junit.xml'),'--basetemp='+str(tmp)]
            result['command']=cmd
            with (out/'stdout.log').open('wb') as stdout,(out/'stderr.log').open('wb') as stderr:
                proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,start_new_session=True)
                result['supervised_pid']=proc.pid
                reason=None
                while proc.poll() is None:
                    ram=memory(); current=members(proc.pid); elapsed=time.monotonic()-started
                    result['samples'].append({'seconds':round(elapsed,3),'available_bytes':ram['available_bytes'],
                                              'processes':current})
                    if ram['available_bytes']<FLOOR: reason='system memory floor'
                    elif any(max(s['rss_bytes'],s['private_bytes'])>CAP for s in current): reason='process memory cap'
                    elif elapsed>=TIMEOUT: reason='timeout'
                    elif sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>3*MiB: reason='evidence size guard'
                    if reason: break
                    time.sleep(0.05)
                result['reason']=reason
                result['status']='PASS' if not reason and proc.poll()==0 else 'FAIL'
    except BaseException as exc:
        result.update(status='FAIL',reason=f'{type(exc).__name__}: {exc}')
    finally:
        if proc is not None:
            try:
                result['active_after_cleanup']=finish_group(proc)
                result['exit_code']=proc.returncode
                if result['active_after_cleanup']: result['status']='FAIL'
            except BaseException as exc:
                result['status']='FAIL'
                result['cleanup_error']=f'{type(exc).__name__}: {exc}'
        result['elapsed_seconds']=round(time.monotonic()-started,3)
        result['postflight']=memory()
        record=out/'processes.json'
        if record.exists():
            info=json.loads(record.read_text())
            result['nodes_started']=any('started_utc_ns' in r for r in info['events'])
        (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        hashes={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in out.rglob('*') if p.is_file()}
        (out/'SHA256.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','command')},indent=2))
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('scenario',choices=CASES)
    raise SystemExit(main(parser.parse_args().scenario))
