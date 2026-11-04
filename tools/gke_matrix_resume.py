"""Continue only unexecuted cells after the documented expired operator token.

No deployment creation/retry, no accepted-cell repeat. Mandatory small loads first.
"""
import json
import time
from datetime import datetime, timezone
import gke_runtime as g


def main():
    g.bounded()
    marker = g.OUT / 'matrix-strategy-correction-start.json'
    assert not marker.exists(), 'No automatic retry'
    rows = json.loads((g.OUT / 'MATRIX_INDEX.json').read_text())
    g.save(marker.name, {'utc': datetime.now(timezone.utc).isoformat(),
        'reason': 'Confirmed DNS Service timeout and mixed-profile readiness deadlock; targeted DNS /32 and coordinated OnDelete rollout',
        'preserved_cells': len(rows), 'priority': '1/2/5/10 first; 50/101 stress only afterward'})
    refresh = time.monotonic()
    try:
        for loads in ((1, 2, 5, 10), (50, 101)):
            for n in (1, 3, 5):
                for d in (1, 2, 3):
                    todo = [c for c in loads if not any(r['nodes']==n and r['difficulty']==d and r['concurrency']==c for r in rows)]
                    if not todo: continue
                    # Reserve 30 minutes before the hard two-hour deadline for export/deletion.
                    if g.bounded() > 75*60:
                        g.save('MATRIX_STRATEGY_CORRECTION_RESULT.json', {'execution':'TIME_BUDGET_STOP','cells':len(rows)})
                        return
                    if time.monotonic()-refresh > 15*60:
                        g.connect(); refresh=time.monotonic()
                    name=f'n{n}-d{d}'
                    g.release(n,d,name)
                    for c in todo:
                        g.bounded()
                        if c >= 50: time.sleep(61)
                        prefix=f'cell-{name}-c{c}'
                        assert not (g.OUT/(prefix+'.json')).exists(), 'Preserve original cell'
                        before=[g.probe(prefix+'-resume-resources-before-'+str(i),'resources',pod='hisjb-'+str(i)) for i in range(n)]
                        result=g.probe(prefix,'cell',c,timeout=180)
                        after=[g.probe(prefix+'-resume-resources-after-'+str(i),'resources',pod='hisjb-'+str(i)) for i in range(n)]
                        result['api_cpu_seconds_delta_all_nodes']=sum(a['api_cpu_seconds']-b['api_cpu_seconds'] for a,b in zip(after,before))
                        result['api_rss_bytes_all_nodes_after']=sum(a['api_rss_bytes'] for a in after)
                        result['resource_samples_before']=before; result['resource_samples_after']=after
                        g.save(prefix+'.json',result)
                        rows.append({'file':prefix+'.json','nodes':n,'difficulty':d,'concurrency':c,'status':result['status'],'errors':result['errors']})
                        g.save('MATRIX_INDEX.json',rows)
        g.save('MATRIX_STRATEGY_CORRECTION_RESULT.json',{'execution':'COMPLETED','cells':len(rows)})
    except BaseException as exc:
        g.save('MATRIX_STRATEGY_CORRECTION_RESULT.json',{'execution':'STOPPED','cells':len(rows),'error_type':type(exc).__name__,'reason':str(exc)[:200]})
        raise

if __name__=='__main__': main()
