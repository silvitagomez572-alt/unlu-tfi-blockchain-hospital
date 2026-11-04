"""Remove the old RollingUpdate field before the authorized OnDelete strategy."""
import json
import gke_runtime as g
g.bounded()
sts=json.loads(g.kube('strategy-before',['get','statefulset','hisjb','-o','json']))
assert sts['metadata']['uid']=='58b7eb0e-207c-4538-9972-ce8335c63894'
assert sts['metadata']['labels']['project']=='hisjb-tfi'
patch=json.dumps([{'op':'test','path':'/metadata/uid','value':sts['metadata']['uid']},
    {'op':'replace','path':'/spec/updateStrategy','value':{'type':'OnDelete'}}])
args=['patch','statefulset','hisjb','--type=json','-p',patch,'-o','json']
g.kube('strategy-dry-run',args+['--dry-run=server'])
g.kube('strategy-corrected',args)
g.kube('dns-after-policy',['exec','-i','hisjb-1','--','python','-B','-'],
    stdin=(g.ROOT/'tools/gke_dns_probe.py').read_bytes(),timeout=25)
g.kube('headless-service-diagnostic',['get','service','hisjb-headless','-o','json'])
g.kube('headless-endpointslices',['get','endpointslices','-l','kubernetes.io/service-name=hisjb-headless','-o','json'])
