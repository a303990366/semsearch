"""查詢：語義 cosine 為主 + 關鍵字小額加分，每個檔案只留最相關的一段。"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .extract import fmt_t
from .i18n import tr

FTS_BONUS = 0.04   # 純 RRF 會讓 "dog" 這種短字的字面命中壓過真正最像的圖片


@dataclass
class Result:
    path: str
    kind: str          # 檔案類型 text/pdf/docx/image/audio/video
    modality: str      # 命中的 chunk 類型 text/image/audio
    locator: dict
    snippet: str
    score: float
    cos: float

    @property
    def where(self) -> str:
        if "page" in self.locator:
            return tr("page", n=self.locator["page"])
        if "t" in self.locator:
            return fmt_t(self.locator["t"])
        return ""


def search(store, emb, query: str, k: int = 10, modality: str | None = None,
           use_fts: bool = True, rel_cutoff: float | None = None) -> list[Result]:
    """rel_cutoff：只保留分數 >= 第一名 - rel_cutoff 的結果，砍掉明顯不相關的尾巴。"""
    q = emb.query(query)
    vec_hits = store.vector_search(q, max(200, k * 20))
    fts_hits = store.text_search(query, 50) if use_fts else []

    score, cos = {}, {}
    for cid, s in vec_hits:
        score[cid] = cos[cid] = s
    for r, cid in enumerate(fts_hits):
        if cid not in cos:
            score[cid] = cos[cid] = store.chunk_vec_score(cid, q)
        score[cid] += FTS_BONUS / (1 + r * 0.1)

    seen, results = set(), []
    for cid in sorted(score, key=score.get, reverse=True):
        info = store.chunk_info(cid)
        if not info:
            continue
        path, kind, mod, locator, snippet = info
        if (modality and mod != modality) or path in seen:
            continue
        if rel_cutoff is not None and results and score[cid] < results[0].score - rel_cutoff:
            break
        seen.add(path)
        results.append(Result(path, kind, mod, json.loads(locator), snippet, score[cid], cos[cid]))
        if len(results) >= k:
            break
    return results
