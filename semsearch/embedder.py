"""EmbeddingGemma 2 封裝：文字 / 圖片 / 音訊 都投影到同一個向量空間。"""
from __future__ import annotations

import re
import threading
import time

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from . import config

# 多模態占位符；文件或查詢裡若剛好出現這些字樣（例如原始碼），處理器會以為要接媒體而報錯
_PLACEHOLDER = re.compile(r"<\|(image|video|audio)\|>")


def _sanitize(text: str) -> str:
    return _PLACEHOLDER.sub(lambda m: "<" + m.group(1) + ">", text)


class Embedder:
    def __init__(self, model_id: str = config.MODEL_ID, dim: int = config.DIM,
                 vision: bool = True, audio: bool = True):
        self.dim = dim
        # 搜尋與背景索引共用同一個模型：查詢優先，索引每批之間讓路
        self._lock = threading.Lock()
        self._query_waiting = threading.Event()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # FP16 會產生 NaN，只能用 BF16 或 FP32
        if self.device == "cuda" and torch.cuda.is_bf16_supported():
            dtype = torch.bfloat16
        else:
            dtype = torch.float32
        config_kwargs = {}
        if not vision:
            config_kwargs["vision_config"] = None
        if not audio:
            config_kwargs["audio_config"] = None
        model_kwargs = {"torch_dtype": dtype}
        if self.device == "cuda":
            # 權重直接載到 GPU，避免先在 RAM 放一份完整模型
            model_kwargs["device_map"] = "cuda"
        kwargs = dict(
            device=None if self.device == "cuda" else self.device,
            model_kwargs=model_kwargs,
            config_kwargs=config_kwargs or None,
        )
        try:
            # 已下載過就完全離線載入，不連 Hugging Face
            self.model = SentenceTransformer(model_id, local_files_only=True, **kwargs)
        except Exception:
            self.model = SentenceTransformer(model_id, **kwargs)

    def _encode(self, inputs, batch_size: int, priority: bool = False, **kw) -> np.ndarray:
        if priority:
            self._query_waiting.set()
        else:
            while self._query_waiting.is_set():
                time.sleep(0.02)
        try:
            with self._lock:
                return self._encode_locked(inputs, batch_size, **kw)
        finally:
            if priority:
                self._query_waiting.clear()

    def _encode_locked(self, inputs, batch_size: int, **kw) -> np.ndarray:
        emb = self.model.encode(
            inputs,
            batch_size=batch_size,
            truncate_dim=self.dim,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
            **kw,
        )
        return np.asarray(emb, dtype=np.float32).reshape(-1, self.dim)

    def query(self, text: str) -> np.ndarray:
        return self._encode([_sanitize(text)], 1, priority=True, prompt_name="SearchQuery")[0]

    def documents(self, items: list[tuple[str, str]], batch_size: int = 16) -> np.ndarray:
        """items: [(title, text)]，自己組 Document 前綴，把檔名當 title 放進去。"""
        texts = [_sanitize(f"title: {t or 'none'} | text: {x}") for t, x in items]
        return self._encode(texts, batch_size, prompt="")

    def images(self, images: list) -> np.ndarray:
        """images: PIL.Image 或檔案路徑。"""
        inputs = [{"text": "<|image|>", "image": [im]} for im in images]
        return self._encode_media(inputs)

    def audios(self, clips: list) -> np.ndarray:
        """clips: 16 kHz mono float32 np.ndarray（傳路徑也可以，但會需要 librosa）。"""
        inputs = [{"text": "<|audio|>", "audio": [c]} for c in clips]
        return self._encode_media(inputs)

    def _encode_media(self, inputs: list[dict]) -> np.ndarray:
        # 多模態 dict 輸入不一定支援 batch，逐筆最保險
        if not inputs:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.vstack([self._encode(x, 1, prompt="") for x in inputs])
