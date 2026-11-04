"""Keep the existing localhost-only read tunnel alive until controlled cleanup."""
import subprocess
import gke_runtime as g

if __name__ == '__main__':
    g.bounded()
    with (g.OUT / 'observability-forward-held.log').open('ab') as log:
        child = subprocess.Popen([str(g.KUBECTL), '--context=hisjb-tfi-exclusive',
            '-n', g.NAMESPACE, 'port-forward', '--address=127.0.0.1',
            'pod/hisjb-observability', '19990:9090', '19930:3000'],
            env=g.KENV, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
        g.save('observability-forward.json', {'pid':child.pid, 'held_by_parent':True})
        print('Local authenticated observability tunnel PID '+str(child.pid), flush=True)
        raise SystemExit(child.wait())
