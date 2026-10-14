"""SQLite 索引：檔案表 + chunk 表（向量存 float16 BLOB）+ FTS5 全文（trigram，中英文都能比對）。"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import numpy as np

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT NOT NULL,
    error TEXT
);
CREATE TABLE IF NOT EXISTS chunks(
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    modality TEXT NOT NULL,
    locator TEXT NOT NULL,
    snippet TEXT NOT NULL,
    vec BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(snippet, path, tokenize='trigram');
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

# 索引與搜尋執行緒會同時開連線；切 WAL 與建表需要獨占鎖，不受 busy timeout 保護，所以序列化
_init_lock = threading.Lock()


class Store:
    def __init__(self, db_path: Path = config.DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, timeout=30)
        self.db.execute("PRAGMA foreign_keys=ON")
        with _init_lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            self._check_meta()
        self._mat = None
        self._mat_sig = None

    def _check_meta(self):
        want = {"model": config.MODEL_ID, "dim": str(config.DIM)}
        have = dict(self.db.execute("SELECT key, value FROM meta").fetchall())
        if have and any(have.get(k) != v for k, v in want.items()):
            raise SystemExit(f"索引是用 {have} 建的，現在設定是 {want}；請換 SEMSEARCH_HOME 或刪除 {config.DB_PATH}")
        self.db.executemany("INSERT OR REPLACE INTO meta VALUES(?,?)", want.items())
        self.db.commit()

    # ---- 增量判斷 ----
    def file_state(self, path: str):
        return self.db.execute("SELECT id, mtime, size FROM files WHERE path=?", (path,)).fetchone()

    def known_paths_under(self, root: str) -> list[str]:
        prefix = root.rstrip("\\/") + "\\"
        return [r[0] for r in self.db.execute(
            "SELECT path FROM files WHERE substr(path, 1, ?) = ?", (len(prefix), prefix))]

    def all_paths(self) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT path FROM files")]

    def delete_file(self, path: str):
        row = self.db.execute("SELECT id FROM files WHERE path=?", (path,)).fetchone()
        if not row:
            return
        ids = [r[0] for r in self.db.execute("SELECT id FROM chunks WHERE file_id=?", row)]
        self.db.executemany("DELETE FROM chunks_fts WHERE rowid=?", [(i,) for i in ids])
        self.db.execute("DELETE FROM files WHERE id=?", row)
        self._mat = None

    def put_file(self, path: str, mtime: float, size: int, kind: str,
                 chunks: list, vecs: np.ndarray, error: str | None = None):
        self.delete_file(path)
        cur = self.db.execute(
            "INSERT INTO files(path, mtime, size, kind, error) VALUES(?,?,?,?,?)",
            (path, mtime, size, kind, error))
        fid = cur.lastrowid
        for ch, v in zip(chunks, vecs):
            c = self.db.execute(
                "INSERT INTO chunks(file_id, modality, locator, snippet, vec) VALUES(?,?,?,?,?)",
                (fid, ch.modality, json.dumps(ch.locator), ch.snippet,
                 v.astype(np.float16).tobytes()))
            self.db.execute("INSERT INTO chunks_fts(rowid, snippet, path) VALUES(?,?,?)",
                            (c.lastrowid, ch.snippet if ch.modality == "text" else "", path))
        self._mat = None

    def commit(self):
        self.db.commit()

    # ---- 搜尋 ----
    def _matrix(self):
        # 另一個執行緒（索引器）可能剛寫入，用 (筆數, 最大 id) 判斷快取是否過期
        sig = self.db.execute("SELECT COUNT(*), MAX(id) FROM chunks").fetchone()
        if sig != self._mat_sig:
            self._mat = None
            self._mat_sig = sig
        if self._mat is None:
            rows = self.db.execute("SELECT id, vec FROM chunks").fetchall()
            ids = np.array([r[0] for r in rows], dtype=np.int64)
            mat = (np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float16)
                   .reshape(-1, config.DIM).astype(np.float32)) if rows else np.zeros((0, config.DIM), np.float32)
            self._mat = (ids, mat)
        return self._mat

    def vector_search(self, q: np.ndarray, k: int) -> list[tuple[int, float]]:
        ids, mat = self._matrix()
        if not len(ids):
            return []
        scores = mat @ q
        top = np.argsort(-scores)[:k]
        return [(int(ids[i]), float(scores[i])) for i in top]

    def chunk_vec_score(self, cid: int, q: np.ndarray) -> float:
        row = self.db.execute("SELECT vec FROM chunks WHERE id=?", (cid,)).fetchone()
        return float(np.frombuffer(row[0], dtype=np.float16).astype(np.float32) @ q) if row else 0.0

    def text_search(self, query: str, k: int) -> list[int]:
        terms = [t for t in query.replace('"', " ").split() if len(t) >= 3]
        if not terms:
            return []
        expr = " OR ".join(f'"{t}"' for t in terms)
        try:
            return [r[0] for r in self.db.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?", (expr, k))]
        except sqlite3.OperationalError:
            return []

    def chunk_info(self, cid: int):
        return self.db.execute(
            "SELECT f.path, f.kind, c.modality, c.locator, c.snippet FROM chunks c "
            "JOIN files f ON f.id = c.file_id WHERE c.id=?", (cid,)).fetchone()

    def stats(self):
        return {
            "files": self.db.execute("SELECT kind, COUNT(*) FROM files GROUP BY kind").fetchall(),
            "chunks": self.db.execute("SELECT modality, COUNT(*) FROM chunks GROUP BY modality").fetchall(),
            "errors": self.db.execute("SELECT COUNT(*) FROM files WHERE error IS NOT NULL").fetchone()[0],
        }
