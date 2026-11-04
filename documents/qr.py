"""Bounded single-node grant registry. Tokens are never stored in plaintext."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4
from blockchain.transaction import is_hash, is_uuid


class AccessDenied(ValueError):
    pass


def digest_token(token):
    if not isinstance(token, str) or re.fullmatch(r'[A-Za-z0-9_-]{43}', token) is None:
        raise AccessDenied('access unavailable')
    return hashlib.sha256(token.encode('ascii')).hexdigest()


class QRStore:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = Path(path), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS grants (
                id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                document_id TEXT NOT NULL, version_id TEXT NOT NULL,
                document_hash TEXT NOT NULL, transaction_id TEXT NOT NULL,
                created INTEGER NOT NULL, expires INTEGER NOT NULL,
                max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0,
                revoked INTEGER NOT NULL DEFAULT 0)''')
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('grant storage integrity check failed')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def issue(self, document_id, version_id, document_hash, transaction_id, ttl_seconds=300, max_uses=1):
        if not (is_uuid(document_id) and is_uuid(version_id) and is_hash(document_hash) and is_hash(transaction_id)):
            raise ValueError('invalid grant reference')
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 3600:
            raise ValueError('TTL outside 60..3600 seconds')
        if type(max_uses) is not int or not 1 <= max_uses <= 10:
            raise ValueError('query limit outside 1..10')
        now, token, grant_id = int(self.clock()), secrets.token_urlsafe(32), str(uuid4())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM grants').fetchone()[0] >= 10000:
                raise ValueError('grant storage capacity reached')
            db.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?,?,?,0,0)',
                       (grant_id, digest_token(token), document_id, version_id, document_hash,
                        transaction_id, now, now + ttl_seconds, max_uses))
        return {'grant_id': grant_id, 'token': token, 'created_at': now,
                'expires_at': now + ttl_seconds, 'max_uses': max_uses, 'uses': 0, 'revoked': False}

    def resolve(self, token, verifier):
        hashed, now = digest_token(token), int(self.clock())
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM grants WHERE token_hash=?', (hashed,)).fetchone()
            if row is None or row['revoked'] or row['uses'] >= row['max_uses']:
                raise AccessDenied('access unavailable')
            if now < row['created'] or now >= row['expires']:
                db.execute('UPDATE grants SET revoked=1 WHERE id=?', (row['id'],))
                db.commit()
                raise AccessDenied('access unavailable')
            # Verifier holds a chain read lock and never performs network requests.
            result = verifier(dict(row))
            db.execute('UPDATE grants SET uses=uses+1 WHERE id=?', (row['id'],))
            return {'verification': result, 'uses': row['uses'] + 1,
                    'remaining_uses': row['max_uses'] - row['uses'] - 1, 'expires_at': row['expires']}

    def revoke(self, token):
        hashed = digest_token(token)
        with self.connect() as db:
            return db.execute('UPDATE grants SET revoked=1 WHERE token_hash=?', (hashed,)).rowcount > 0
