"""Close only the remaining mandatory cells; never repeat a cell or run stress."""
import hashlib
import json
from datetime import datetime, timezone
import gke_runtime as g


def main():
    rows=json.loads((g.OUT/'MATRIX_INDEX.json').read_text())
    missing=[(n,d,c) for n in (1,3,5) for d in (1,2,3) for c in (1,2,5,10)
             if not any(r['nodes']==n and r['difficulty']==d and r['concurrency']==c for r in rows)]
    if not missing:
        print('All 36 mandatory cells already recorded; no tests executed.'); return
    assert len(missing)<=4 and all(n==5 and d==3 for n,d,c in missing)
    assert g.bounded()<80*60, 'Reserve at least 40 minutes of the two-hour window'
    marker=g.OUT/'required-closure-start.json'
    assert not marker.exists(), 'No automatic retry'
    g.save(marker.name,{'utc':datetime.now(timezone.utc).isoformat(),'missing':missing,
      'index_before_sha256':hashlib.sha256((g.OUT/'MATRIX_INDEX.json').read_bytes()).hexdigest(),
      'reason':'Only final mandatory profile after conservative batch boundary; no extra stress; hard two-hour limit unchanged'})
    try:
        g.connect(); g.release(5,3,'n5-d3')
        for n,d,c in missing:
            assert g.bounded()<85*60, 'Stop tests and reserve cleanup'
            prefix=f'cell-n{n}-d{d}-c{c}'
            assert not (g.OUT/(prefix+'.json')).exists()
            before=[g.probe(prefix+'-closure-resources-before-'+str(i),'resources',pod='hisjb-'+str(i)) for i in range(n)]
            result=g.probe(prefix,'cell',c,timeout=180)
            after=[g.probe(prefix+'-closure-resources-after-'+str(i),'resources',pod='hisjb-'+str(i)) for i in range(n)]
            result['api_cpu_seconds_delta_all_nodes']=sum(a['api_cpu_seconds']-b['api_cpu_seconds'] for a,b in zip(after,before))
            result['api_rss_bytes_all_nodes_after']=sum(a['api_rss_bytes'] for a in after)
            result['resource_samples_before']=before;result['resource_samples_after']=after
            g.save(prefix+'.json',result)
            rows.append({'file':prefix+'.json','nodes':n,'difficulty':d,'concurrency':c,'status':result['status'],'errors':result['errors']})
            g.save('MATRIX_INDEX.json',rows)
        g.save('MATRIX_REQUIRED_FINAL.json',{'execution':'COMPLETED','utc':datetime.now(timezone.utc).isoformat(),
            'mandatory_recorded':sum(r['concurrency']<=10 for r in rows),'no_additional_stress':True})
    except BaseException as exc:
        g.save('MATRIX_REQUIRED_FINAL.json',{'execution':'STOPPED','reason':str(exc)[:250],
            'mandatory_recorded':sum(r['concurrency']<=10 for r in rows)})
        raise

if __name__=='__main__': main()
