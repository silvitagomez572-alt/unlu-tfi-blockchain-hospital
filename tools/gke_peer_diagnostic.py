"""Read-only DNS/HTTP diagnostic, run inside an existing pod."""
import json, socket, time, urllib.request, urllib.error
from pathlib import Path
results=[]
for host in ('hisjb-0.hisjb-headless.tfi-hospital.svc.cluster.local','hisjb-1.hisjb-headless.tfi-hospital.svc.cluster.local','hisjb-2.hisjb-headless.tfi-hospital.svc.cluster.local'):
    started=time.monotonic()
    try:
        addresses=socket.getaddrinfo(host,19980,type=socket.SOCK_STREAM)
        row={'host':host,'dns_seconds':time.monotonic()-started,'addresses':sorted({a[4][0] for a in addresses})}
        try:
            with urllib.request.urlopen('http://'+host+':19980/healthz',timeout=3) as r: row['health']=json.load(r)
        except Exception as exc: row['http_error']=type(exc).__name__+': '+str(exc)
    except Exception as exc: row={'host':host,'dns_error':type(exc).__name__+': '+str(exc)}
    results.append(row)
print(json.dumps({'resolv':Path('/etc/resolv.conf').read_text(),'results':results}))
