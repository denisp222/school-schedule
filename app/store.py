"""Durable local storage with optimistic locking and version history."""
from __future__ import annotations

import json
import sqlite3
import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .model import validate_state

SNAPSHOT_LIMIT=15


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path: Path | str, initializer):
        self.path = Path(path)
        self._backup_lock = threading.Lock()
        self._mutations = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS snapshots ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL, "
                "label TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS current_state ("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
                "revision INTEGER NOT NULL, payload TEXT NOT NULL)"
            )
            if not db.execute("SELECT 1 FROM current_state").fetchone():
                state = validate_state(initializer())
                payload = json.dumps(state, ensure_ascii=False)
                db.execute("INSERT INTO current_state VALUES (1,1,?)", (payload,))
                db.execute("INSERT INTO snapshots(created,label,payload) VALUES (?,?,?)",
                           (self.now(), "Исходное расписание", payload))
            self._prune(db)

    @staticmethod
    def _prune(db):
        db.execute('DELETE FROM snapshots WHERE id NOT IN (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?) AND id<>(SELECT MIN(id) FROM snapshots)',(SNAPSHOT_LIMIT,))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            with db:
                yield db
        finally:
            db.close()

    def backup(self):
        """Keep one independent, consistent SQLite copy; never copy a live WAL."""
        with self._backup_lock:
            target = self.path.with_suffix(self.path.suffix + '.bak')
            temporary = target.with_suffix('.tmp')
            try:
                with self.connect() as source:
                    destination = sqlite3.connect(temporary)
                    try:
                        source.backup(destination)
                    finally:
                        destination.close()
                os.replace(temporary, target)
            except (OSError, sqlite3.Error):
                logging.exception('Independent project backup failed')
                try:temporary.unlink(missing_ok=True)
                except OSError:pass

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def read(self) -> dict:
        with self.connect() as db:
            revision, payload = db.execute(
                "SELECT revision,payload FROM current_state WHERE singleton=1"
            ).fetchone()
            saved_at = db.execute('SELECT created FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()[0]
        state=json.loads(payload)
        from .class_hours import fill_leaders
        fill_leaders(state)
        return {"revision": revision, "state": state, "savedAt": saved_at}

    def last_saved_at(self):
        """Read a header timestamp without decoding the entire school project."""
        with self.connect() as db:
            saved=db.execute('SELECT created FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()[0]
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='assistant_threads'").fetchone():
                latest=db.execute('SELECT MAX(updated) FROM assistant_threads').fetchone()[0]
                return max(saved,latest or '')
            return saved

    def mutate(self, revision: int, label: str, fn,*,extra=None) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current_revision, payload = db.execute(
                "SELECT revision,payload FROM current_state WHERE singleton=1"
            ).fetchone()
            if current_revision != revision:
                raise Conflict("Данные изменились в другом окне. Обновите страницу и повторите.")
            state = json.loads(payload)
            result = fn(state)
            state = state if result is None else result
            state = validate_state(state)
            encoded = json.dumps(state, ensure_ascii=False)
            latest=db.execute('SELECT id FROM snapshots ORDER BY id DESC LIMIT 1').fetchone()[0]
            initial=db.execute('SELECT MIN(id) FROM snapshots').fetchone()[0]
            if encoded==payload and latest!=initial:
                db.execute('UPDATE snapshots SET created=? WHERE id=?',(self.now(),latest))
            else:
                db.execute("INSERT INTO snapshots(created,label,payload) VALUES (?,?,?)",(self.now(),label,encoded))
            db.execute("UPDATE current_state SET revision=?,payload=? WHERE singleton=1",
                       (current_revision + 1, encoded))
            if extra:extra(db)
            self._prune(db)
        self._mutations += 1
        if self._mutations == 1 or self._mutations % 20 == 0:
            self.backup()
        return {"revision": current_revision + 1, "state": state, "savedAt": self.now()}

    def history(self, limit: int = SNAPSHOT_LIMIT+1) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,created,label FROM snapshots ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"id": row[0], "created": row[1], "label": row[2]} for row in rows]

    def snapshot(self, ident: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT payload FROM snapshots WHERE id=?", (int(ident),)).fetchone()
        if not row:
            raise ValueError("Версия не найдена.")
        return json.loads(row[0])
