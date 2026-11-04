"""Ephemeral Prometheus/Grafana on the existing TFI VM; no extra cloud resources."""
import argparse, base64, json, secrets, subprocess, time, urllib.request
from pathlib import Path
from gke_runtime import ROOT, OUT, PRIVATE, NAMESPACE, KENV, KUBECTL, kube, bounded, save

OBS = ROOT / 'infrastructure/observability'
OBS.mkdir(parents=True, exist_ok=True)

def apply(name, obj, secret=False):
    raw = json.dumps(obj).encode()
    if not secret: (OBS / (name + '.json')).write_bytes(raw)
    kube('observability-' + name, ['apply', '-f', '-'], stdin=raw)

def targets(n, scenario):
    groups = [{'targets':[f'hisjb-{i}.hisjb-headless.{NAMESPACE}.svc.cluster.local:19980'],
        'labels':{'node':f'hisjb-{i}','scenario':scenario}} for i in range(n)]
    apply('targets', {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'hisjb-prom-targets'},
        'data':{'targets.json':json.dumps(groups)}})

def start():
    bounded()
    assert not (OUT/'observability-start.json').exists()
    password = secrets.token_urlsafe(30)
    (PRIVATE/'grafana-password.txt').write_text(password)
    apply('secret', {'apiVersion':'v1','kind':'Secret','metadata':{'name':'hisjb-grafana'},
        'type':'Opaque','stringData':{'password':password}}, secret=True)
    config={'global':{'scrape_interval':'5s','evaluation_interval':'5s'},'rule_files':['/config/rules.yml'],
        'scrape_configs':[{'job_name':'hisjb','file_sd_configs':[{'files':['/targets/targets.json'],'refresh_interval':'5s'}]}]}
    rules={'groups':[{'name':'hisjb','rules':[{'alert':'HISJBPendingTransactions','expr':'pow_mempool_transactions > 0',
        'for':'10s','labels':{'severity':'warning'},'annotations':{'summary':'Transacciones pendientes de minado en {{ $labels.node }}'}},
        {'alert':'HISJBNodeDown','expr':'up{job="hisjb"} == 0','for':'15s','labels':{'severity':'critical'}}]}]}
    apply('prom-config',{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'hisjb-prom-config'},
        'data':{'prometheus.yml':json.dumps(config),'rules.yml':json.dumps(rules)}})
    targets(1,'demo')
    datasource={'apiVersion':1,'datasources':[{'name':'Prometheus HISJB','uid':'hisjb-prom','type':'prometheus',
        'access':'proxy','url':'http://127.0.0.1:9090','isDefault':True,'editable':False}]}
    provider={'apiVersion':1,'providers':[{'name':'HISJB','type':'file','options':{'path':'/dashboards'}}]}
    panels=[]
    for i,(title,expr,unit) in enumerate([
        ('Altura por nodo','pow_block_height','short'),('Peers disponibles','pow_peers_connected','short'),
        ('Pendientes','pow_mempool_transactions','short'),('Tiempo medio de minería (ventana 5m)',
         'rate(pow_mining_duration_seconds_sum[5m]) / rate(pow_mining_duration_seconds_count[5m])','s'),
        ('Targets UP','up{job="hisjb"}','short'),('Sincronizaciones','pow_sync_total','short')]):
        panels.append({'id':i+1,'title':title,'type':'timeseries','datasource':{'type':'prometheus','uid':'hisjb-prom'},
            'gridPos':{'x':12*(i%2),'y':8*(i//2),'w':12,'h':8},'targets':[{'expr':expr,'legendFormat':'{{node}} · {{scenario}}','refId':'A'}],
            'fieldConfig':{'defaults':{'unit':unit},'overrides':[]}})
    dashboard={'uid':'hisjb-tfi-gke','title':'HISJB Evidence Chain · GKE temporal','schemaVersion':39,'version':1,
        'timezone':'utc','refresh':'5s','time':{'from':'now-15m','to':'now'},'panels':panels,
        'description':'Datos Prometheus reales del clúster hisjb-tfi-temp. CPU y latencia se miden aparte en JSON experimental.'}
    apply('graf-config',{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'hisjb-graf-config'},
        'data':{'datasources.yml':json.dumps(datasource),'providers.yml':json.dumps(provider),'dashboard.json':json.dumps(dashboard)}})
    volumes=[{'name':'prom-config','configMap':{'name':'hisjb-prom-config'}},{'name':'targets','configMap':{'name':'hisjb-prom-targets'}},
        {'name':'graf-config','configMap':{'name':'hisjb-graf-config'}},{'name':'prom-data','emptyDir':{'sizeLimit':'256Mi'}},
        {'name':'graf-data','emptyDir':{'sizeLimit':'128Mi'}}]
    containers=[{'name':'prometheus','image':'quay.io/prometheus/prometheus:v3.15.0-distroless',
        'args':['--config.file=/config/prometheus.yml','--storage.tsdb.path=/prometheus','--storage.tsdb.retention.time=2h'],
        'ports':[{'containerPort':9090}], 'resources':{'requests':{'cpu':'50m','memory':'128Mi'},'limits':{'cpu':'300m','memory':'384Mi'}},
        'volumeMounts':[{'name':'prom-config','mountPath':'/config','readOnly':True},{'name':'targets','mountPath':'/targets','readOnly':True},
            {'name':'prom-data','mountPath':'/prometheus'}],
        'readinessProbe':{'httpGet':{'path':'/-/ready','port':9090},'periodSeconds':5}},
      {'name':'grafana','image':'grafana/grafana:13.2.3-distroless','ports':[{'containerPort':3000}],
        'env':[{'name':'GF_SECURITY_ADMIN_PASSWORD','valueFrom':{'secretKeyRef':{'name':'hisjb-grafana','key':'password'}}},
          {'name':'GF_PLUGINS_PREINSTALL_DISABLED','value':'true'},{'name':'GF_AUTH_ANONYMOUS_ENABLED','value':'false'},
          {'name':'GF_ANALYTICS_REPORTING_ENABLED','value':'false'},{'name':'LANG','value':'en_US.UTF-8'}],
        'resources':{'requests':{'cpu':'50m','memory':'128Mi'},'limits':{'cpu':'500m','memory':'512Mi'}},
        'volumeMounts':[{'name':'graf-data','mountPath':'/var/lib/grafana'},
          {'name':'graf-config','mountPath':'/etc/grafana/provisioning/datasources/hisjb.yml','subPath':'datasources.yml','readOnly':True},
          {'name':'graf-config','mountPath':'/etc/grafana/provisioning/dashboards/hisjb.yml','subPath':'providers.yml','readOnly':True},
          {'name':'graf-config','mountPath':'/dashboards/hisjb.json','subPath':'dashboard.json','readOnly':True}],
        'readinessProbe':{'httpGet':{'path':'/api/health','port':3000},'initialDelaySeconds':10,'periodSeconds':5}}]
    for c in containers: c['securityContext']={'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}
    apply('pod',{'apiVersion':'v1','kind':'Pod','metadata':{'name':'hisjb-observability','labels':{'project':'hisjb-tfi','app':'hisjb-observability'}},
        'spec':{'automountServiceAccountToken':False,'securityContext':{'runAsNonRoot':True,'runAsUser':472,'fsGroup':472},
          'containers':containers,'volumes':volumes}})
    apply('isolation',{'apiVersion':'networking.k8s.io/v1','kind':'NetworkPolicy','metadata':{'name':'hisjb-observability-isolation'},
        'spec':{'podSelector':{'matchLabels':{'app':'hisjb-observability'}},'policyTypes':['Ingress'],'ingress':[]}})
    kube('observability-ready',['wait','--for=condition=Ready','pod/hisjb-observability','--timeout=180s'],timeout=200)
    save('observability-start.json',{'status':'READY','namespace':NAMESPACE,'extra_vm':False,'extra_disks':False})
    forward()

def forward():
    bounded()
    import socket
    for port in (19990,19930):
        with socket.socket() as sock: sock.bind(('127.0.0.1',port))
    log=(OUT/'observability-forward.log').open('ab')
    p=subprocess.Popen([str(KUBECTL),'--context=hisjb-tfi-exclusive','-n',NAMESPACE,'port-forward','--address=127.0.0.1',
        'pod/hisjb-observability','19990:9090','19930:3000'],env=KENV,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    log.close(); save('observability-forward.json',{'pid':p.pid})

def capture(label):
    bounded()
    for suffix in ('targets','rules','query?query=pow_block_height','query?query=ALERTS'):
        url='http://127.0.0.1:19990/api/v1/'+suffix
        with urllib.request.urlopen(url, timeout=15) as r: result=json.load(r)
        save('prom-'+label+'-'+suffix.split('?')[0]+('-height' if 'height' in suffix else '-alerts' if 'ALERTS' in suffix else '')+'.json',result)
    password=(PRIVATE/'grafana-password.txt').read_text()
    req=urllib.request.Request('http://127.0.0.1:19930/api/user',headers={'Authorization':'Basic '+base64.b64encode(('admin:'+password).encode()).decode()})
    with urllib.request.urlopen(req,timeout=10) as r: user=json.load(r)
    save('grafana-auth-'+label+'.json',{'authenticated':user.get('login')=='admin','dashboard_uid':'hisjb-tfi-gke'})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['start','forward','capture']);p.add_argument('--label',default='demo');a=p.parse_args()
    capture(a.label) if a.stage=='capture' else globals()[a.stage]()
