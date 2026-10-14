"""把各種檔案拆成可嵌入的 chunk，並保留「位置」（頁碼 / 時間碼）以便結果能直接跳轉。

媒體一律在記憶體內解碼（Pillow / PyAV），不寫暫存檔、不依賴外部 ffmpeg。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from . import config

SAMPLE_RATE = 16000
SILENCE_RMS = 0.003
MAX_IMAGE_SIDE = 1536
FRAME_SIDE = 768
SCANNED_PAGE_DPI = 110
MAX_SCANNED_PAGES = 200
MIN_PAGE_TEXT = 20     # 頁面抽出的文字少於這個長度，視為掃描頁，改用圖片嵌入


class SkipFile(Exception):
    """這個檔案不處理（例如有密碼保護），不算失敗。"""


@dataclass
class Chunk:
    modality: str          # text / image / audio
    payload: Any           # str（文字）/ PIL.Image（圖片）/ np.ndarray 16kHz mono（音訊）
    locator: dict = field(default_factory=dict)   # {"page": 3} / {"t": 83.0}
    snippet: str = ""      # 給 FTS 與結果顯示用


def file_kind(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in config.TEXT_EXT:
        return "text"
    if ext in config.PDF_EXT:
        return "pdf"
    if ext in config.DOCX_EXT:
        return "docx"
    if ext in config.IMAGE_EXT:
        return "image"
    if ext in config.AUDIO_EXT:
        return "audio"
    if ext in config.VIDEO_EXT:
        return "video"
    return None


def split_text(text: str, size: int = config.TEXT_CHUNK_CHARS,
               overlap: int = config.TEXT_CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        # 盡量在換行或句號處切
        if end < len(text):
            cut = max(text.rfind("\n", start + size // 2, end),
                      text.rfind("。", start + size // 2, end),
                      text.rfind(". ", start + size // 2, end))
            if cut > start:
                end = cut + 1
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [c for c in out if c]


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-16", "cp950", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def extract(path: Path, kind: str) -> list[Chunk]:
    if kind == "text":
        return [Chunk("text", c, {}, c) for c in split_text(_read_text(path))]
    if kind == "pdf":
        return _pdf(path)
    if kind == "docx":
        import docx
        d = docx.Document(str(path))
        text = "\n".join(p.text for p in d.paragraphs)
        return [Chunk("text", c, {}, c) for c in split_text(text)]
    if kind == "image":
        return [Chunk("image", load_image(path), {}, path.name)]
    if kind == "audio":
        return _audio_segments(path)
    if kind == "video":
        return _video_frames(path) + _audio_segments(path)
    return []


# ---------------------------------------------------------------- PDF

def _pdf(path: Path) -> list[Chunk]:
    import pymupdf
    from PIL import Image
    chunks, scanned = [], 0
    with pymupdf.open(path) as doc:
        if doc.needs_pass and not doc.authenticate(""):
            raise SkipFile("PDF 有密碼保護")
        for i, page in enumerate(doc, start=1):
            text = page.get_text()
            if len(text.strip()) >= MIN_PAGE_TEXT:
                chunks += [Chunk("text", c, {"page": i}, c) for c in split_text(text)]
            elif page.get_images() and scanned < MAX_SCANNED_PAGES:
                # 掃描頁：整頁轉成圖片交給模型（模型看得懂圖中文字）
                pix = page.get_pixmap(dpi=SCANNED_PAGE_DPI)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                chunks.append(Chunk("image", img, {"page": i}, f"{path.name} 第 {i} 頁（掃描）"))
                scanned += 1
    return chunks


# ---------------------------------------------------------------- 圖片

_heif_ready = False


def load_image(path: Path):
    global _heif_ready
    from PIL import Image, ImageOps
    if not _heif_ready:
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            pass
        _heif_ready = True
    with Image.open(path) as im:
        im.draft("RGB", (MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))   # JPEG 直接以較小尺寸解碼，快很多
        im = ImageOps.exif_transpose(im).convert("RGB")
    im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    return im


# ---------------------------------------------------------------- 影音（PyAV）

def _audio_segments(path: Path) -> list[Chunk]:
    import av
    seg_len = config.AUDIO_SEGMENT_SEC * SAMPLE_RATE
    chunks, buf, n_buf = [], [], 0

    seg_idx = 0

    def flush():
        nonlocal buf, n_buf, seg_idx
        t = seg_idx * config.AUDIO_SEGMENT_SEC
        seg_idx += 1
        if n_buf >= SAMPLE_RATE:                # 不足 1 秒的尾巴丟掉
            clip = np.concatenate(buf)[:seg_len]
            # 靜音段落會跟任何查詢都有一點相似，乾脆不索引
            if float(np.sqrt(np.mean(clip ** 2))) >= SILENCE_RMS:
                chunks.append(Chunk("audio", clip, {"t": t}, f"{path.name} @ {fmt_t(t)}"))
        buf, n_buf = [], 0

    with av.open(str(path)) as container:
        if not container.streams.audio:
            return []
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        stream = container.streams.audio[0]
        frames = container.decode(stream)
        for frame in _safe(frames):
            for out in resampler.resample(frame):
                a = out.to_ndarray().reshape(-1)
                while len(a):
                    take = min(len(a), seg_len - n_buf)
                    buf.append(a[:take])
                    n_buf += take
                    a = a[take:]
                    if n_buf >= seg_len:
                        flush()
        for out in resampler.resample(None):
            buf.append(out.to_ndarray().reshape(-1))
            n_buf += out.samples
        flush()
    return chunks


def _video_frames(path: Path) -> list[Chunk]:
    import av
    chunks = []
    with av.open(str(path)) as container:
        if not container.streams.video:
            return []
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        dur = float(stream.duration * stream.time_base) if stream.duration else (
            container.duration / av.time_base if container.duration else 0.0)
        if dur <= 0:
            return []
        every = max(config.VIDEO_FRAME_EVERY_SEC, dur / config.VIDEO_MAX_FRAMES)
        t = min(every / 2, dur / 2)
        while t < dur:
            frame = _frame_at(container, stream, t)
            if frame is not None:
                img = frame.to_image()
                img.thumbnail((FRAME_SIDE, FRAME_SIDE))
                chunks.append(Chunk("image", img, {"t": round(t, 1)}, f"{path.name} @ {fmt_t(t)}"))
            t += every
    return chunks


def _frame_at(container, stream, t: float):
    """跳到 t 之前最近的關鍵影格，再往後解碼到 t。"""
    container.seek(int(t / stream.time_base) + (stream.start_time or 0), stream=stream, backward=True)
    last = None
    for frame in _safe(container.decode(stream)):
        last = frame
        if frame.time is None or frame.time >= t:
            break
    return last


def _safe(frames):
    """壞掉的影格／封包直接略過，不要讓整個檔案失敗。"""
    import av
    while True:
        try:
            yield next(frames)
        except StopIteration:
            return
        except av.error.InvalidDataError:
            continue


def fmt_t(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 \
        else f"{sec // 60:02d}:{sec % 60:02d}"
