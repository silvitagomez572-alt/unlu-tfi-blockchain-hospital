"""Revocable, expiring bearer grants; persist only token hashes, never raw tokens."""
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4
from blockchain.transaction import is_uuid,is_hash

class GrantDenied(ValueError): pass

class GrantStore:
    def __init__(self,path,clock=time.time):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.clock=clock
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS grants (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                document_id TEXT NOT NULL, version_id TEXT NOT NULL, document_hash TEXT NOT NULL,
                created INTEGER NOT NULL, expires INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)''')

    def connect(self):
        db=sqlite3.connect(self.path,timeout=2)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        return db

    def issue(self,document_id,version_id,document_hash,ttl):
        if not (is_uuid(document_id) and is_uuid(version_id) and is_hash(document_hash)):
            raise ValueError('invalid synthetic document reference')
        if type(ttl) is not int or not 60<=ttl<=3600: raise ValueError('TTL must be 60..3600 seconds')
        now=int(self.clock()); grant_id=str(uuid4()); token=secrets.token_urlsafe(32)
        hashed=hashlib.sha256(token.encode('ascii')).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM grants').fetchone()[0]>=10000:
                raise ValueError('grant capacity reached; preserve and review archive')
            db.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?,0)',
                       (grant_id,hashed,document_id,version_id,document_hash,now,now+ttl))
        return {'grant_id':grant_id,'token':token,'expires_at':now+ttl}

    def resolve(self,token):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
            raise GrantDenied('access unavailable')
        hashed=hashlib.sha256(token.encode('ascii')).hexdigest()
        now=int(self.clock())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM grants WHERE token_hash=?',(hashed,)).fetchone()
            if row is None or row['revoked']: raise GrantDenied('access unavailable')
            if now<row['created'] or now>=row['expires']:
                db.execute('UPDATE grants SET revoked=1 WHERE id=?',(row['id'],))
                db.commit()  # Expiry stays denied even if the wall clock moves backward later.
                raise GrantDenied('access unavailable')
            return {key:row[key] for key in ('document_id','version_id','document_hash')}

    def revoke(self,grant_id):
        # UUIDv4 ids are management references, never credentials.
        if not is_uuid(grant_id): raise ValueError('invalid grant id')
        with self.connect() as db:
            return db.execute('UPDATE grants SET revoked=1 WHERE id=?',(grant_id,)).rowcount>0
