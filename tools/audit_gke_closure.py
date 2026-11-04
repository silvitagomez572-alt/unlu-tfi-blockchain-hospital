"""Read preserved results; do not invoke tests, mining or cloud resources."""
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/phase4/gke-runtime-20261104'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    a=json.loads((OUT/'ANALISIS_CARGA.json').read_text())
    core=[r for r in a['cells'] if r['category']=='core']
    assert len({(r['nodes'],r['difficulty'],r['concurrency']) for r in core})==len(core)
    for row in a['cells']:
        assert sha(ROOT/row['source'])==row['sha256']
        assert row['accepted_missing']==0 and row['accepted_duplicated']==0
        assert row['all_chain_duplicate_ids']==0 and row['full_chains_equal']
        if row['category']=='core':
            assert row['status']=='PASS' and row['accepted']==row['concurrency'] and row['rejected_http']==0
    approved=json.loads((ROOT/'evidence/phase2/APPROVED_CORE_SHA256.json').read_text())
    for path,digest in approved.items():assert sha(ROOT/path)==digest,path
    captures=json.loads((ROOT/'evidence/EVIDENCIAS_VISUALES.json').read_text())['captures']
    for item in captures:
        path=ROOT/'evidence'/item['file'];assert sha(path)==item['sha256']
        with Image.open(path) as image:image.verify()
    docker=ROOT/'evidence/phase4/preflight-20261104/41876907701/13347147385'
    original_docker=json.loads((docker/'MANIFIESTO_SHA256.json').read_text())
    for path in sorted(docker.glob('*.png')):
        assert sha(path)==original_docker[path.name]
        with Image.open(path) as image:image.verify()
        captures.append({'file':path.relative_to(ROOT/'evidence').as_posix(),'captured_utc':None,
            'date':'2026-11-04','time_note':'Exact capture timestamp not recorded; date belongs to preserved runner',
            'scenario':'Docker isolated runner, one node; not GKE',
            'description':path.stem,'source':'GitHub Actions 41876907701 / Chromium original screenshot','sha256':sha(path)})
    result={'utc':datetime.now(timezone.utc).isoformat(),'status':'PASS' if len(core)==36 else 'PARTIAL',
        'mandatory_executed':len(core),'mandatory_required':36,'mandatory_pass':sum(r['status']=='PASS' for r in core),
        'accepted_core':sum(r['accepted'] for r in core),'confirmed_core_exactly_once':sum(r['confirmed_exactly_once_each_node'] for r in core),
        'accepted_lost':a['lost_accepted'],'accepted_duplicated':a['duplicated_accepted'],
        'core_source_hashes_unchanged':len(approved),'original_screenshots_verified':len(captures),
        'gke_screenshots':sum('GKE' in r['file'] for r in captures),
        'scope':'Offline evidence validation; no tests repeated; no claim of institutional identity or five independent machines'}
    exports=OUT/'export-verified.json'
    if exports.exists():
        record=json.loads(exports.read_text())
        for row in record['files']:
            p=OUT/row['file'];assert sha(p)==row['sha256']
            if p.suffix=='.json':json.loads(p.read_bytes())
        result['exported_files_hash_verified']=len(record['files'])
    (OUT/'INTEGRIDAD_CIERRE.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'INDICE_CAPTURAS_CONSOLIDADO.json').write_text(json.dumps({'captures':captures},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
