"""Windows-only resource guard. Terminates only the child it just created."""
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

ROOT = Path(__file__).resolve().parents[1]
MiB = 1024**2


class Memory(c.Structure):
    _fields_ = [('length', w.DWORD), ('load', w.DWORD)] + [(name, c.c_ulonglong) for name in
                ('total', 'available', 'page_total', 'page_available', 'virtual_total', 'virtual_available', 'extended')]


class Basic(c.Structure):
    _fields_ = [('process_time', c.c_longlong), ('job_time', c.c_longlong), ('flags', w.DWORD),
                ('min_ws', c.c_size_t), ('max_ws', c.c_size_t), ('active', w.DWORD),
                ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class IO(c.Structure):
    _fields_ = [(name, c.c_ulonglong) for name in ('ro', 'wo', 'oo', 'rt', 'wt', 'ot')]


class Extended(c.Structure):
    _fields_ = [('basic', Basic), ('io', IO), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]


class Counters(c.Structure):
    _fields_ = [('size', w.DWORD), ('faults', w.DWORD)] + [(name, c.c_size_t) for name in
                ('peak_ws', 'ws', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]


kernel = c.WinDLL('kernel32', use_last_error=True)
psapi = c.WinDLL('psapi', use_last_error=True)
kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
kernel.CreateJobObjectW.restype = w.HANDLE
kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
kernel.CloseHandle.argtypes = [w.HANDLE]
psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, c.c_void_p, w.DWORD]


def memory():
    value = Memory()
    value.length = c.sizeof(value)
    if not kernel.GlobalMemoryStatusEx(c.byref(value)):
        raise c.WinError(c.get_last_error())
    return {'total_bytes': value.total, 'available_bytes': value.available, 'used_percent': value.load}


GROUPS = {
 'protocol': ['test_canonical_roundtrip_and_network_domain', 'test_difficulty_retargets_fast_slow_and_exact_boundaries',
              'test_mining_records_attempts_and_does_not_mutate_input', 'test_attempt_and_time_budgets_are_enforced',
              'test_configuration_and_size_limits'],
 'validation': ['test_mutated_block_is_rejected', 'test_remined_wrong_difficulty_and_genesis_are_rejected',
                'test_hash_without_proof_is_rejected', 'test_transaction_schema_rejects_invalid_metadata',
                'test_unknown_fields_and_payload_tampering_are_rejected',
                'test_exact_replay_rejected_inside_and_across_blocks', 'test_future_tx_and_cross_network_tx_rejected_before_mining'],
 'forks_document': ['test_fork_choice_uses_verified_work_not_length', 'test_tie_break_and_invalid_candidate_order',
                    'test_document_integrity_detects_changes_missing_and_conflicts'],
}


def main():
    group = sys.argv[1]
    tests = GROUPS[group]
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = ROOT / 'evidence/tests' / f'{stamp}-{group}'
    out.mkdir(parents=True)
    preflight = memory()
    summary = {'group': group, 'started_utc': stamp, 'preflight': preflight, 'test_functions': tests,
               'timeout_seconds': 12, 'traceback_seconds': 6, 'process_cap_bytes': 192*MiB,
               'min_start_available_bytes': 640*MiB, 'stop_below_available_bytes': 384*MiB,
               'samples': [], 'status': 'BLOCKED'}
    if preflight['available_bytes'] < 640*MiB:
        summary['reason'] = 'insufficient available Windows RAM'
    else:
        job = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x100 | 0x2000  # process committed memory + kill-on-close
        info.process_memory = 192*MiB
        if not job or not kernel.SetInformationJobObject(job, 9, c.byref(info), c.sizeof(info)):
            raise c.WinError(c.get_last_error())
        env = dict(os.environ)
        env.update({'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                    'PYTHONPATH': os.pathsep.join([str(ROOT / '.runtime/test-tools'), str(ROOT)]),
                    'TEMP': str(ROOT / '.runtime'), 'TMP': str(ROOT / '.runtime')})
        args = [sys.executable, '-B', str(ROOT / 'tools/pytest_entry.py'),
                *[f'tests/unit/test_core.py::{name}' for name in tests],
                '-q', '-p', 'no:cacheprovider', '--junitxml=' + str(out / 'junit.xml'),
                '--basetemp=' + str(ROOT / '.runtime' / stamp)]
        summary['command'] = args
        started = time.monotonic()
        proc = None
        reason = None
        peak = 0
        try:
            with (out / 'stdout.log').open('wb') as stdout, (out / 'stderr.log').open('wb') as stderr:
                proc = subprocess.Popen(args, cwd=ROOT, env=env, stdout=stdout, stderr=stderr)
                summary['pid'] = proc.pid
                if not kernel.AssignProcessToJobObject(job, w.HANDLE(int(proc._handle))):
                    proc.kill()
                    proc.wait()
                    raise c.WinError(c.get_last_error())
                while proc.poll() is None:
                    counter = Counters()
                    counter.size = c.sizeof(counter)
                    if not psapi.GetProcessMemoryInfo(w.HANDLE(int(proc._handle)), c.byref(counter), c.sizeof(counter)):
                        reason = 'memory telemetry unavailable'
                        break
                    current = memory()
                    peak = max(peak, counter.peak_ws)
                    elapsed = time.monotonic() - started
                    summary['samples'].append({'elapsed_seconds': round(elapsed, 3), 'working_set_bytes': counter.ws,
                                               'private_bytes': counter.private, 'available_bytes': current['available_bytes']})
                    if elapsed >= 12:
                        reason = 'timeout'
                    elif max(counter.ws, counter.private) > 192*MiB:
                        reason = 'process memory limit'
                    elif current['available_bytes'] < 384*MiB:
                        reason = 'Windows available memory below floor'
                    if reason:
                        break
                    time.sleep(0.05)
                if reason and proc.poll() is None:
                    proc.kill()
                summary['exit_code'] = proc.wait(timeout=2)
                counter = Counters()
                counter.size = c.sizeof(counter)
                if psapi.GetProcessMemoryInfo(w.HANDLE(int(proc._handle)), c.byref(counter), c.sizeof(counter)):
                    peak = max(peak, counter.peak_ws)
        finally:
            kernel.CloseHandle(job)
        summary.update({'elapsed_seconds': round(time.monotonic() - started, 3),
                        'peak_working_set_bytes': peak, 'status': 'PASS' if summary.get('exit_code') == 0 and not reason else 'FAIL',
                        'interruption_reason': reason, 'postflight': memory()})
    (out / 'result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out / 'SHA256.json').write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('command','samples','test_functions')}, indent=2))
    print(f'Evidence: {out}')
    return 0 if summary['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
