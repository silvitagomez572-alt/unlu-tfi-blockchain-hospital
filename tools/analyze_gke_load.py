"""Offline analysis of real HTTP evidence. Never sends requests or repeats tests."""
from collections import Counter
import csv,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/phase4/gke-runtime-20261104'

def analyze():
    result=[]
    for index in json.loads((OUT/'MATRIX_INDEX.json').read_text()):
        path=OUT/index['file'];r=json.loads(path.read_text())
        responses=r['requests'];codes=Counter(str(x.get('http')) for x in responses)
        accepted=[x['body']['transaction_id'] for x in responses if x.get('http')==202]
        counters=[Counter(t['tx_id'] for b in c['blocks'] for t in b['transactions']) for c in r['final_chains']]
        missing=[tx for tx in accepted if any(count[tx]==0 for count in counters)]
        duplicates=[tx for tx in accepted if any(count[tx]>1 for count in counters)]
        all_dupes=[dict((tx,n) for tx,n in count.items() if n>1) for count in counters]
        classifications=Counter()
        for response in responses:
            code=response.get('http')
            if code==202:continue
            if code is None:category='transport_'+response.get('error_type','unknown')
            elif code==503 and response.get('body')=='Service Unavailable':category='server_concurrency_limit_503'
            elif code in (400,413,422):category='input_validation_'+str(code)
            elif code==409:category='conflict_409_requires_detail'
            elif code==429:category='rate_limit_429'
            else:category='unclassified_'+str(code)
            classifications[category]+=1
        cpu_percent=None
        if r.get('resource_samples_before'):
            cpu_percent=sum(100*(a['api_cpu_seconds']-b['api_cpu_seconds'])/(a['monotonic']-b['monotonic'])
                for a,b in zip(r['resource_samples_after'],r['resource_samples_before']))
        mined=r.get('mined');mb=mined['body'] if mined else {}
        pending_after=r.get('pending_after')
        row={'nodes':r['nodes'],'difficulty':r['difficulty'],'concurrency':r['concurrency'],
          'category':'core' if r['concurrency']<=10 else 'stress','status':r['status'],
          'requests_sent':len(responses),'http_responses_received':sum(x.get('http') is not None for x in responses),
          'accepted':len(accepted),'rejected_http':sum(x.get('http') not in (None,202) for x in responses),
          'unknown_transport_outcome':sum(x.get('http') is None for x in responses),
          'confirmed_exactly_once_each_node':sum(all(count[tx]==1 for count in counters) for tx in accepted),
          'accepted_missing':len(missing),'accepted_duplicated':len(duplicates),
          'all_chain_duplicate_ids':sum(len(x) for x in all_dupes),
          'full_chains_equal':r['full_chains_equal'],'full_validation_executed':True,
          'latency_mean_seconds':r['latency_mean_seconds'],'latency_p95_seconds':r['latency_p95_seconds'],
          'throughput_accepted_per_second':r['throughput_accepted_per_second'],
          'mining_seconds':mb.get('elapsed_seconds'),'mining_attempts':mb.get('attempts'),
          'hash_rate_attempts_per_second':r['hash_rate_attempts_per_second'],
          'propagation_observed_seconds':r['propagation_observed_seconds'],'sync_observed_seconds':r['sync_observed_seconds'],
          'cpu_core_percent_sample_window':cpu_percent,'rss_mib_after_all_apis':r.get('api_rss_bytes_all_nodes_after',0)/(1024**2),
          'pending_after_each_node':','.join(str(len(x['body'])) if x['http']==200 else 'unavailable' for x in pending_after) if pending_after else '',
          'http_codes':json.dumps(codes,sort_keys=True),'rejection_causes':json.dumps(classifications,sort_keys=True),
          'source':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        result.append(row)
    if result:
        with (ROOT/'MATRIZ_EXPERIMENTAL.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
    report={'utc':datetime.now(timezone.utc).isoformat(),'cells':result,
       'core_executed':sum(r['category']=='core' for r in result),'core_required':36,
       'stress_executed':sum(r['category']=='stress' for r in result),
       'lost_accepted':sum(r['accepted_missing'] for r in result),'duplicated_accepted':sum(r['accepted_duplicated'] for r in result),
       'limitations':['HTTP receipt is not application acceptance. HTTP 503 is distinct from a submitted transaction.',
         'CPU is sampled API process CPU over the observed interval, not VM utilization. RSS after is not peak RSS.',
         'p95 nearest-rank; 1/2/5 samples give weak tail inference. One iteration per cell.',
         'Earlier cells did not retain IDs for rejected requests; only accepted IDs can be directly traced there.',
         'The script validates hashes, PoW and complete chains during each cell; this analysis does not rerun mining.',
         'Nodes share one VM. One active miner, not separate worker-pool architectures.']}
    (OUT/'ANALISIS_CARGA.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('cells','limitations')},indent=2))
if __name__=='__main__':analyze()
