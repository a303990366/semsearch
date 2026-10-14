"""用法：
  python -m semsearch app                       # 桌面助手（系統匣 + 全域快捷鍵）
  python -m semsearch index <資料夾> [--no-audio] [--no-video]
  python -m semsearch search "<描述>" [-k 10] [--modality image|text|audio]
  python -m semsearch stats
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from .store import Store


def cmd_index(args):
    from .indexer import index_one, plan
    root = Path(args.folder).resolve()
    skip = set()
    if args.no_audio:
        skip.add("audio")
    if args.no_video:
        skip.add("video")
    store = Store()
    todo, removed = plan(store, [root], skip)
    for sp in removed:
        store.delete_file(sp)
    store.commit()
    print(f"待索引 {len(todo)} 個檔案，移除 {len(removed)} 個已消失的檔案")
    if not todo:
        return

    from .embedder import Embedder
    t0 = time.time()
    emb = Embedder()
    print(f"模型載入 {time.time() - t0:.1f}s（{emb.device}）")

    timing, counts = Counter(), Counter()
    t_all = time.time()
    for i, job in enumerate(todo, 1):
        t = time.time()
        n, err, _ = index_one(store, emb, job)
        if i % 20 == 0:
            store.commit()
        dt = time.time() - t
        timing[job.kind] += dt
        counts[job.kind] += 1
        mark = "!" if err else " "
        print(f"[{i}/{len(todo)}]{mark} {job.kind:5s} {n:4d} chunks {dt:6.2f}s  {job.path.name}"
              + (f"  ← {err}" if err else ""))
    store.commit()
    print(f"\n完成：{len(todo)} 檔，{time.time() - t_all:.1f}s")
    for k in counts:
        print(f"  {k:5s} {counts[k]:5d} 檔  平均 {timing[k] / counts[k]:.2f}s/檔")


def cmd_search(args):
    from .embedder import Embedder
    from .search import search
    store = Store()
    t0 = time.time()
    emb = Embedder()
    t1 = time.time()
    results = search(store, emb, args.query, args.k, args.modality, not args.no_fts)
    t2 = time.time()
    print(f"（模型載入 {t1 - t0:.1f}s，查詢 {(t2 - t1) * 1000:.0f}ms）\n")
    for n, r in enumerate(results, 1):
        where = f" {r.where}" if r.where else ""
        print(f"{n:2d}. [{r.modality:5s} cos={r.cos:.3f}] {r.path}{where}")
        if r.modality == "text":
            s = " ".join(r.snippet.split())
            print(f"      {s[:160]}{'…' if len(s) > 160 else ''}")


def cmd_stats(_):
    print(json.dumps(Store().stats(), ensure_ascii=False, indent=2))


def cmd_app(_):
    from .app import main as app_main
    app_main()


def main():
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="semsearch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("app").set_defaults(fn=cmd_app)
    a = sub.add_parser("index")
    a.add_argument("folder")
    a.add_argument("--no-audio", action="store_true")
    a.add_argument("--no-video", action="store_true")
    a.set_defaults(fn=cmd_index)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("-k", type=int, default=10)
    s.add_argument("--modality", choices=["text", "image", "audio"])
    s.add_argument("--no-fts", action="store_true")
    s.set_defaults(fn=cmd_search)
    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
