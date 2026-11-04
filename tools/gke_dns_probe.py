"""Bounded, read-only queries to the observed cluster DNS service and endpoint."""
import json,socket,struct,time,urllib.request
host='hisjb-2.hisjb-headless.tfi-hospital.svc.cluster.local'
question=b''.join(bytes([len(x)])+x.encode() for x in host.split('.'))+b'\0'+struct.pack('!HH',1,1)
packet=struct.pack('!HHHHHH',12345,256,1,0,0,0)+question
rows=[]
for ip in ('10.74.0.10','10.73.0.6'):
    s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(2)
    try:
        t=time.monotonic();s.sendto(packet,(ip,53));raw,_=s.recvfrom(4096)
        rows.append({'dns':ip,'seconds':time.monotonic()-t,'header':struct.unpack('!HHHHHH',raw[:12])})
    except Exception as exc:rows.append({'dns':ip,'error':type(exc).__name__})
    finally:s.close()
for ip in ('10.73.0.20','10.73.0.22'):
    try:
        with urllib.request.urlopen('http://'+ip+':19980/healthz',timeout=2) as r:rows.append({'pod_ip':ip,'health':json.load(r)})
    except Exception as exc:rows.append({'pod_ip':ip,'error':type(exc).__name__})
print(json.dumps(rows))
