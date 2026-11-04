"""Read-only export through kubectl stdin; SQLite is backed up consistently in RAM."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3

root=Path('/data')
files=[p for p in root.rglob('*') if p.is_file() and p.suffix in ('.json','.jsonl','.sqlite3')]
assert sum(p.stat().st_size for p in files)<100*1024**2
rows=[]
for path in files:
    if path.suffix=='.sqlite3':
        source=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        backup=sqlite3.connect(':memory:')
        source.backup(backup)
        assert backup.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        raw=backup.serialize()
        source.close();backup.close()
        method='SQLite online backup; integrity_check=ok; token hashes only'
    else:
        raw=path.read_bytes();method='Original bytes'
        if path.suffix=='.json':
            json.loads(raw)
        elif path.suffix=='.jsonl':
            for line in raw.splitlines():
                if line.strip(): json.loads(line)
    rows.append({'path':str(path.relative_to(root)),'method':method,
        'sha256':hashlib.sha256(raw).hexdigest(),'base64':base64.b64encode(raw).decode()})
print(json.dumps(rows))
