"""Exactly one pytest node ID per child. Windows Job cap inherited by its nodes."""
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from run_bounded_tests import memory, Extended, Counters, kernel, psapi, MiB

ROOT=Path(__file__).resolve().parents[1]

class Accounting(c.Structure):
    _fields_=[('user',c.c_longlong),('kernel',c.c_longlong),('period_user',c.c_longlong),
              ('period_kernel',c.c_longlong),('faults',w.DWORD),('total',w.DWORD),
              ('active',w.DWORD),('terminated',w.DWORD)]
kernel.QueryInformationJobObject.argtypes=[w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.c_void_p]
kernel.TerminateJobObject.argtypes=[w.HANDLE,w.UINT]

def run(nodeid):
    integration=nodeid.startswith('tests/integration/')
    timeout=90 if integration else 12
    cap=192*MiB
    minimum=(1024 if integration else 640)*MiB
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    name=nodeid.split('::')[-1]
    out=ROOT/'evidence/phase2/tests'/f'{stamp}-{name}'
    out.mkdir(parents=True)
    (ROOT/'.runtime/phase2').mkdir(parents=True,exist_ok=True)
    result={'nodeid':nodeid,'utc':stamp,'timeout_seconds':timeout,'memory_cap_per_process_bytes':cap,
            'resource_profile':'integration: minimum 1 GiB; maximum 192 MiB per process' if integration else 'standard',
            'start_minimum_bytes':minimum,'stop_below_bytes':384*MiB,'preflight':memory(),'status':'BLOCKED',
            'samples':[],'nodes_started':False}
    # Wait briefly for transient Windows memory pressure before creating any child.
    result['memory_wait_samples']=[]
    deadline=time.monotonic()+15
    while result['preflight']['available_bytes']<minimum and time.monotonic()<deadline:
        result['memory_wait_samples'].append(result['preflight'])
        time.sleep(1)
        result['preflight']=memory()
    if result['preflight']['available_bytes']<minimum:
        result['reason']='insufficient Windows available RAM; test not started'
    else:
        job=kernel.CreateJobObjectW(None,None)
        limit=Extended(); limit.basic.flags=0x100|0x2000; limit.process_memory=cap
        if not job or not kernel.SetInformationJobObject(job,9,c.byref(limit),c.sizeof(limit)):
            raise c.WinError(c.get_last_error())
        env=dict(os.environ)
        env.update({'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONDONTWRITEBYTECODE':'1',
                    'PYTHONPATH':os.pathsep.join([str(ROOT/'.runtime/runtime-tools'),str(ROOT/'.runtime/test-tools'),str(ROOT)]),
                    'TFI_EVIDENCE_DIR':str(out),'TFI_INTEGRATION':'1' if integration else '0',
                    'TFI_PROCESS_CAP_BYTES':str(cap),
                    'TEMP':str(ROOT/'.runtime'),'TMP':str(ROOT/'.runtime')})
        args=[sys.executable,'-B',str(ROOT/'tools/phase2_pytest_entry.py'),nodeid,'-q','-s','-p','no:cacheprovider',
              '--junitxml='+str(out/'junit.xml'),'--basetemp='+str(ROOT/'.runtime/phase2'/stamp)]
        result['command']=args; started=time.monotonic(); peak=0; reason=None
        try:
            with (out/'stdout.log').open('wb') as stdout,(out/'stderr.log').open('wb') as stderr:
                proc=subprocess.Popen(args,cwd=ROOT,env=env,stdout=stdout,stderr=stderr)
                result['pid']=proc.pid
                if not kernel.AssignProcessToJobObject(job,w.HANDLE(int(proc._handle))):
                    proc.kill(); proc.wait(); raise c.WinError(c.get_last_error())
                while proc.poll() is None:
                    counter=Counters(); counter.size=c.sizeof(counter)
                    if not psapi.GetProcessMemoryInfo(w.HANDLE(int(proc._handle)),c.byref(counter),c.sizeof(counter)):
                        reason='process memory telemetry unavailable'; break
                    peak=max(peak,counter.peak_ws)
                    ram=memory()['available_bytes']; elapsed=time.monotonic()-started
                    result['samples'].append({'seconds':round(elapsed,3),'working_set_bytes':counter.ws,
                                              'private_bytes':counter.private,'available_bytes':ram})
                    if ram<384*MiB: reason='Windows memory floor'
                    elif max(counter.ws,counter.private)>cap: reason='process memory cap'
                    elif elapsed>=timeout: reason='timeout'
                    if reason: break
                    time.sleep(0.05)
                if reason:
                    kernel.TerminateJobObject(job,1)
                result['exit_code']=proc.wait(timeout=3)
                result['status']='PASS' if result['exit_code']==0 and not reason else 'FAIL'
                result['reason']=reason
        finally:
            # Only processes in this newly created Job. Never global PIDs/services.
            kernel.TerminateJobObject(job,0)
            acct=Accounting()
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                if not kernel.QueryInformationJobObject(job,1,c.byref(acct),c.sizeof(acct),None):
                    raise c.WinError(c.get_last_error())
                if not acct.active: break
                time.sleep(0.05)
            result['active_processes_after_cleanup']=acct.active
            result['job_total_processes']=acct.total
            kernel.CloseHandle(job)
        result.update({'elapsed_seconds':round(time.monotonic()-started,3),'peak_test_working_set_bytes':peak,
                       'postflight':memory()})
        if result['active_processes_after_cleanup']:
            result['status']='FAIL'
    process_record=out/'processes.json'
    if process_record.exists():
        info=json.loads(process_record.read_text())
        result['nodes_started']=any('started_utc_ns' in event for event in info['events'])
        result['node_memory']=info['memory']
        result['active_nodes_reported']=info['active_after_cleanup']
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    manifest={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in out.rglob('*') if p.is_file()}
    (out/'SHA256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','command')},indent=2))
    print('Evidence:',out,flush=True)
    return result['status']=='PASS'

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('nodeid'); args=parser.parse_args()
    if not args.nodeid.startswith(('tests/unit/test_phase2.py::','tests/integration/test_phase2_network.py::')):
        raise SystemExit('Only phase-2 tests allowed')
    raise SystemExit(0 if run(args.nodeid) else 1)
