"""Windows 內建 OCR（Windows.Media.Ocr）：免安裝、離線、支援系統已安裝的語言套件。"""
from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger("semsearch.ocr")

_CJK = "぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯　-〿"
_CJK_GAP = re.compile(f"(?<=[{_CJK}]) +(?=[{_CJK}])")
_CJK_CHAR = re.compile(f"[{_CJK}]")
_MEANINGFUL = re.compile(f"[A-Za-z0-9{_CJK}]")
MIN_CHARS = 6          # 少於這麼多有效字元視為雜訊（一般照片常會辨識出零星符號）

try:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage import FileAccessMode, StorageFile
    _TAGS = [l.language_tag for l in OcrEngine.available_recognizer_languages]
    MAX_DIM = OcrEngine.max_image_dimension
except Exception as e:  # 非 Windows 或缺套件就停用 OCR
    log.warning("OCR unavailable: %s", e)
    _TAGS, MAX_DIM = [], 0

# 有中日韓語言就先用它（它也認得英文），沒有 CJK 字再改用英文引擎（英文斷詞較好）
_CJK_TAG = next((t for t in _TAGS if t.split("-")[0] in ("zh", "ja", "ko")), None)
_LATIN_TAG = next((t for t in _TAGS if t.startswith("en")), None) or next(
    (t for t in _TAGS if t != _CJK_TAG), None)


def available() -> bool:
    return bool(_TAGS)


async def _recognize(path: str, tag: str) -> str:
    f = await StorageFile.get_file_from_path_async(path)
    stream = await f.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    engine = OcrEngine.try_create_from_language(Language(tag))
    result = await engine.recognize_async(bitmap)
    return "\n".join(line.text for line in result.lines)


def ocr_image(path: str) -> str:
    """回傳辨識出的文字；沒有有效文字回傳空字串。path 需為 Windows 可解碼的 png/jpg/bmp。"""
    if not _TAGS:
        return ""
    text = ""
    try:
        if _CJK_TAG:
            text = asyncio.run(_recognize(path, _CJK_TAG))
            if len(_CJK_CHAR.findall(text)) >= 2:
                text = _CJK_GAP.sub("", text)
            elif _LATIN_TAG:
                text = asyncio.run(_recognize(path, _LATIN_TAG))
        else:
            text = asyncio.run(_recognize(path, _LATIN_TAG))
    except Exception as e:
        log.warning("OCR failed for %s: %s", path, e)
        return ""
    text = text.strip()
    return text if len(_MEANINGFUL.findall(text)) >= MIN_CHARS else ""
