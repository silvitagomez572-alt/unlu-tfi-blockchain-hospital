"""Transfer the existing deadline guard to immediate, scoped export and cleanup."""
import json
from datetime import datetime, timezone
import gke_runtime as g

if __name__=='__main__':
    guard=json.loads((g.OUT/'deadline-guard.json').read_text())
    pid=guard['pid']; assert type(pid) is int and pid>0
    # Stop only the verified standby controller. No app/service is stopped here.
    script=("$running = @(Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
      "Where-Object { $_.CommandLine -match '(gke_matrix_resume|gke_finish_required)\\.py' }); "
      "if ($running.Count -ne 0) { throw 'Tests still running; preserve deadline guard' }; "
      "$guard = Get-CimInstance Win32_Process -Filter 'ProcessId = "+str(pid)+"'; "
      "if ($guard) { if ($guard.Name -ne 'python.exe' -or $guard.CommandLine -notlike '*unlu-tfi-blockchain-hospital*' "
      "-or $guard.CommandLine -notlike '*gke_runtime.py guard') { throw 'Guard identity mismatch' }; "
      "Stop-Process -Id "+str(pid)+" -ErrorAction Stop }")
    g.command('deadline-guard-handoff',['powershell','-NoProfile','-NonInteractive','-Command',script],timeout=30)
    g.save('GUARD_HANDOFF.json',{'utc':datetime.now(timezone.utc).isoformat(),'previous_guard_pid':pid,
       'action':'Immediate export and deletion replaces waiting; hard two-hour limit unchanged'})
    try:
        g.cleanup()
    except BaseException as exc:
        g.save('CLEANUP_ERROR.json',{'utc':datetime.now(timezone.utc).isoformat(),'error':str(exc)[:400]})
        raise
