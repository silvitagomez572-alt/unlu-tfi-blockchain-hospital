"""Preserve real metrics and dashboard definitions before deleting temporary GKE."""
import base64,json,time,urllib.parse,urllib.request
from datetime import datetime,timezone
from pathlib import Path
import gke_runtime as g

def read(url,headers=None):
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers or {}),timeout=15) as response:return json.load(response)

def main():
    folder=g.OUT/'observability-export'
    if folder.exists():
        folder=g.OUT/('observability-export-'+datetime.now(timezone.utc).strftime('%H%M%S'))
    folder.mkdir(exist_ok=False)
    start=json.loads((g.PRIVATE/'runtime-start.json').read_text())['epoch']
    end=time.time()
    queries={'height':'pow_block_height','peers':'pow_peers_connected','pending':'pow_mempool_transactions',
      'mining_sum':'pow_mining_duration_seconds_sum','mining_count':'pow_mining_duration_seconds_count',
      'up':'up{job="hisjb"}','sync':'pow_sync_total','peer_errors':'pow_peer_events_total',
      'validation_errors':'pow_validation_errors_total','alerts':'ALERTS'}
    for name,expr in queries.items():
        result=read('http://127.0.0.1:19990/api/v1/query_range?'+urllib.parse.urlencode({'query':expr,'start':start,'end':end,'step':5}))
        (folder/(name+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    for item in ('targets','rules','status/runtimeinfo'):
        (folder/(item.replace('/','-')+'.json')).write_text(json.dumps(read('http://127.0.0.1:19990/api/v1/'+item),indent=2),encoding='utf-8')
    password=(g.PRIVATE/'grafana-password.txt').read_text()
    headers={'Authorization':'Basic '+base64.b64encode(('admin:'+password).encode()).decode()}
    data=read('http://127.0.0.1:19930/api/dashboards/uid/hisjb-tfi-gke',headers)
    assert data['dashboard']['uid']=='hisjb-tfi-gke'
    (folder/'grafana-dashboard.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
    (folder/'METADATA.json').write_text(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'start':start,'end':end,
       'source':'Real in-cluster Prometheus via authenticated kubectl localhost tunnel','step_seconds':5,'graphs_are_not_screenshots':True},indent=2))
    print(json.dumps({'files':len(list(folder.glob('*.json'))),'dashboard_uid':data['dashboard']['uid'],'folder':str(folder)}))

if __name__=='__main__':main()
