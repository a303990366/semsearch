"""掃描資料夾 → 找出新增/變更/刪除的檔案 → 拆 chunk → 嵌入 → 寫入索引。CLI 與桌面助手共用。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config
from .extract import SkipFile, extract, file_kind

# 先做便宜的（文字類幾秒就能搜），再做圖片、音訊，最耗時的影片放最後
KIND_ORDER = {"text": 0, "docx": 0, "pdf": 1, "image": 2, "audio": 3, "video": 4}


@dataclass
class Job:
    path: Path
    kind: str
    mtime: float
    size: int


def _norm(p) -> str:
    return os.path.normcase(os.path.abspath(str(p))).rstrip("\\/")


def iter_files(root: Path, excludes: set[str] = frozenset()):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in config.SKIP_DIRS and not d.startswith(".")
                       and _norm(os.path.join(dirpath, d)) not in excludes]
        for name in filenames:
            p = Path(dirpath) / name
            kind = file_kind(p)
            if kind:
                yield p, kind


def plan(store, roots: list[Path], skip_kinds: set[str] = frozenset(),
         prune_all: bool = False, excludes: list[str] = ()) -> tuple[list[Job], list[str]]:
    """回傳 (待索引, 待移除)。prune_all=True 時，不在任何 roots 底下的舊索引也一併移除。"""
    ex = {_norm(e) for e in excludes}
    todo, seen = [], set()
    for root in roots:
        for p, kind in iter_files(root, ex):
            if kind in skip_kinds:
                continue
            sp = str(p)
            try:
                st = p.stat()
            except OSError:
                continue
            limit = config.MAX_TEXT_MB if kind == "text" else config.MAX_FILE_MB
            if st.st_size > limit * 1024 * 1024:
                continue
            seen.add(sp)
            row = store.file_state(sp)
            if row and row[1] == st.st_mtime and row[2] == st.st_size:
                continue
            todo.append(Job(p, kind, st.st_mtime, st.st_size))
    if prune_all:
        known = store.all_paths()
    else:
        known = [sp for r in roots for sp in store.known_paths_under(str(r))]
    removed = [sp for sp in known if sp not in seen]
    todo.sort(key=lambda j: (KIND_ORDER.get(j.kind, 9), j.size))
    return todo, removed


def index_one(store, emb, job: Job) -> tuple[int, str | None, bool]:
    """索引單一檔案，回傳 (chunk 數, 錯誤訊息, 是否為略過)。
    失敗會記錄在索引裡（檔案沒變就不重試），不會中斷整體。"""
    err, skipped = None, False
    chunks, vecs = [], np.zeros((0, emb.dim), np.float32)
    try:
        chunks = extract(job.path, job.kind)
        vecs = embed_chunks(emb, job.path, chunks)
    except SkipFile as e:
        err, skipped = f"略過：{e}", True
        chunks, vecs = [], np.zeros((0, emb.dim), np.float32)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        chunks, vecs = [], np.zeros((0, emb.dim), np.float32)
    store.put_file(str(job.path), job.mtime, job.size, job.kind, chunks, vecs, err)
    return len(chunks), err, skipped


def embed_chunks(emb, path: Path, chunks) -> np.ndarray:
    out = np.zeros((len(chunks), emb.dim), dtype=np.float32)
    groups = {"text": [], "image": [], "audio": []}
    for idx, c in enumerate(chunks):
        groups[c.modality].append(idx)
    if groups["text"]:
        out[groups["text"]] = emb.documents([(path.name, chunks[i].payload) for i in groups["text"]])
    if groups["image"]:
        out[groups["image"]] = emb.images([chunks[i].payload for i in groups["image"]])
    if groups["audio"]:
        out[groups["audio"]] = emb.audios([chunks[i].payload for i in groups["audio"]])
    return out
