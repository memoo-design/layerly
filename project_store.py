"""Private, capability-protected images with durable sliding expiration.

SQLite write transactions serialize reads/renewals/deletion across processes.
Only registered UUID directories and our one known file may be removed.
"""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class ProjectStore:
    def __init__(self, root, retention=86400, clock=time.time):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention = max(300, int(retention))
        self.clock = clock
        with self.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, token TEXT NOT NULL, expires REAL NOT NULL)')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.root / 'projects.sqlite3', timeout=30)
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def path(self, project_id):
        if not re.fullmatch('[0-9a-f]{32}', project_id):
            raise FileNotFoundError('Unknown project')
        directory = self.root / project_id
        if directory.is_symlink() or directory.resolve() != directory:
            raise FileNotFoundError('Unsafe project directory')
        path = directory / 'cleaned.png'
        if path.is_symlink() or path.resolve() != path:
            raise FileNotFoundError('Unsafe project file')
        return path

    def create(self, png):
        project_id, token = uuid.uuid4().hex, secrets.token_urlsafe(32)
        with self.transaction() as db:
            # Commit ownership before writing, so a crash leaves a cleanable record.
            db.execute('INSERT INTO projects VALUES (?, ?, ?)',
                       (project_id, hashlib.sha256(token.encode()).hexdigest(), self.clock() + self.retention))
        with self.transaction() as db:
            if not db.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
                raise OSError('Project expired before it could be saved')
            db.execute('UPDATE projects SET expires=? WHERE id=?', (self.clock()+self.retention, project_id))
            path = self.path(project_id)
            path.parent.mkdir()
            path.write_bytes(png)
        return project_id, token

    def access(self, project_id, token, read=True):
        path = self.path(project_id)
        with self.transaction() as db:
            row = db.execute('SELECT token, expires FROM projects WHERE id=?', (project_id,)).fetchone()
            digest = hashlib.sha256(token.encode()).hexdigest()
            if not row or row[1] <= self.clock() or not hmac.compare_digest(row[0], digest):
                raise FileNotFoundError('Project expired or access denied')
            # Read under the same lock as cleanup; Flask sends independent bytes.
            data = path.read_bytes() if read else None
            db.execute('UPDATE projects SET expires=? WHERE id=?', (self.clock() + self.retention, project_id))
            return data

    def cleanup(self):
        removed = 0
        with self.transaction() as db:
            for (project_id,) in db.execute('SELECT id FROM projects WHERE expires<=?', (self.clock(),)).fetchall():
                try:
                    path = self.path(project_id)
                    # Never recursively remove directories or unknown files.
                    path.unlink(missing_ok=True)
                    if path.parent.exists() and not any(path.parent.iterdir()):
                        path.parent.rmdir()
                    db.execute('DELETE FROM projects WHERE id=?', (project_id,))
                    removed += 1
                except (OSError, FileNotFoundError):
                    continue
        return removed
