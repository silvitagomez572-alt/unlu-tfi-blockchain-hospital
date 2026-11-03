"""Prepared CI evidence packager; no executions, network calls or state changes."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main(scenario):
    base=ROOT/'evidence/consensus-ci'
    target=ROOT/'evidence/consensus-ci-export'/scenario
    target.mkdir(parents=True,exist_ok=False)
    files=[]
    for directory in (base/'setup',base/scenario):
        if directory.exists(): files.extend(p for p in directory.rglob('*') if p.is_file())
    bad=[]
    source_manifest=base/scenario/'SHA256.json'
    if source_manifest.exists():
        for name,digest in json.loads(source_manifest.read_text()).items():
            if sha(base/scenario/name)!=digest: bad.append(name)
    core=json.loads((ROOT/'evidence/phase2/APPROVED_CORE_SHA256.json').read_text())
    changed=[name for name,digest in core.items() if sha(ROOT/name)!=digest]
    selected=['node/state.py','tests/integration/test_phase2_network.py',
              'tools/run_consensus_linux.py','tools/package_consensus_ci.py',
              'tools/phase2_pytest_entry.py','.github/workflows/tfi-consensus.yml',
              'requirements-node.txt','requirements-test.txt','evidence/phase2/APPROVED_CORE_SHA256.json']
    selected+=list(core)
    for name in selected:
        if name.endswith('.py'): ast.parse((ROOT/name).read_text(encoding='utf-8'))
    result_path=base/scenario/'result.json'
    result=json.loads(result_path.read_text()) if result_path.exists() else {'status':'BLOCKED','reason':'Test supervisor did not run; inspect setup/workflow log'}
    archive=target/f'CONSENSO_{scenario}_EVIDENCIAS.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in sorted(files): z.write(path,'records/'+path.relative_to(base).as_posix())
        for name in selected: z.write(ROOT/name,'source/'+name)
    with zipfile.ZipFile(archive) as z: corrupt=z.testzip()
    manifest={'utc':datetime.now(timezone.utc).isoformat(),'scenario':scenario,
              'functional_status':result['status'],'hash_mismatches':bad,'core_mismatches':changed,
              'archive_corrupt_member':corrupt,'archive_sha256':sha(archive),
              'records':{p.relative_to(base).as_posix():sha(p) for p in sorted(files)},
              'sources':{name:sha(ROOT/name) for name in selected}}
    (target/'MANIFIESTO_SHA256.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    size=sum(p.stat().st_size for p in target.iterdir() if p.is_file())
    allowed=size<=2*1024**2
    # Keep originals in the VM even if too large; never truncate to claim success.
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as f:
            f.write('upload='+str(allowed).lower()+'\n')
    print(json.dumps({'scenario':scenario,'bytes':size,'upload_allowed':allowed,
                      'hash_mismatches':bad,'core_mismatches':changed,'zip_corrupt':corrupt,
                      'functional_status':result['status']},indent=2))
    return 0 if allowed and not bad and not changed and corrupt is None else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('scenario',choices=['A','B'])
    raise SystemExit(main(parser.parse_args().scenario))
