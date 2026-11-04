"""Export Prometheus through a short-lived, exclusive tunnel; no Grafana dependency."""
import json,subprocess,time,urllib.parse,urllib.request
from datetime import datetime,timezone
import gke_runtime as g

def read(url):
    with urllib.request.urlopen(url,timeout=15) as r:return json.load(r)

if __name__=='__main__':
    g.kube('observability-final-pod',['get','pod','hisjb-observability','-o','json'])
    g.kube('observability-grafana-previous',['logs','hisjb-observability','-c','grafana','--previous','--tail=100'],check=False)
    folder=g.OUT/('observability-final-'+datetime.now(timezone.utc).strftime('%H%M%S'))
    folder.mkdir(exist_ok=False)
    with (folder/'tunnel.log').open('wb') as log:
        child=subprocess.Popen([str(g.KUBECTL),'--context=hisjb-tfi-exclusive','-n',g.NAMESPACE,
            'port-forward','--address=127.0.0.1','pod/hisjb-observability','19990:9090'],env=g.KENV,
            stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(20):
                try:read('http://127.0.0.1:19990/api/v1/status/runtimeinfo');break
                except OSError:
                    assert child.poll() is None,'Tunnel exited'
                    time.sleep(.5)
            start=json.loads((g.PRIVATE/'runtime-start.json').read_text())['epoch'];end=time.time()
            queries={'height':'pow_block_height','peers':'pow_peers_connected','pending':'pow_mempool_transactions',
                'mining_sum':'pow_mining_duration_seconds_sum','mining_count':'pow_mining_duration_seconds_count',
                'up':'up{job="hisjb"}','sync':'pow_sync_total','peer_errors':'pow_peer_events_total',
                'validation_errors':'pow_validation_errors_total','alerts':'ALERTS'}
            for name,expr in queries.items():
                data=read('http://127.0.0.1:19990/api/v1/query_range?'+urllib.parse.urlencode({'query':expr,'start':start,'end':end,'step':5}))
                assert data['status']=='success'
                (folder/(name+'.json')).write_text(json.dumps(data,indent=2))
            for name in ('targets','rules','status/runtimeinfo'):
                (folder/(name.replace('/','-')+'.json')).write_text(json.dumps(read('http://127.0.0.1:19990/api/v1/'+name),indent=2))
            targets=json.loads((folder/'targets.json').read_text())['data']['activeTargets']
            g.save('FINAL_PROMETHEUS_EXPORT.json',{'utc':datetime.now(timezone.utc).isoformat(),'folder':folder.name,
                'targets':len(targets),'up':sum(t['health']=='up' for t in targets),
                'grafana_current_availability_not_assumed':True,'previous_dashboard_and_screenshot_preserved':True})
            print('Final Prometheus export: '+str(len(targets))+' targets, '+str(sum(t['health']=='up' for t in targets))+' UP',flush=True)
        finally:
            if child.poll() is None:child.terminate()
            child.wait(timeout=15)
