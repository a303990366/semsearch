"""驗證：圖片 / 音訊 能嵌入，且文字查詢能跨模態對上。"""
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from semsearch.embedder import Embedder  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

td = ROOT / "testdata"
t = time.time()
e = Embedder()
print(f"load {time.time() - t:.1f}s on {e.device}")

img_names = [f"IMG_000{i}.jpg" for i in range(1, 6)]   # 斑馬 / 貓 / 艾菲爾鐵塔 / 披薩 / 黃金獵犬
t = time.time()
imgs = e.images([str(td / n) for n in img_names])
print(f"images {imgs.shape} finite={np.isfinite(imgs).all()} {(time.time() - t) / len(img_names):.2f}s/img")

au = None
try:
    t = time.time()
    au = e.audios([str(td / "rec_01.wav"), str(td / "rec_02.wav")])   # 睡眠 / 股市
    print(f"audio {au.shape} {(time.time() - t) / 2:.2f}s/clip")
except Exception:
    import traceback
    traceback.print_exc()

print(f"\n{'query':38s} " + " ".join(f"{n[4:8]:>5s}" for n in img_names) + "   rec1  rec2")
for q in ["a zebra", "a dog", "a cat", "pizza", "Eiffel tower", "斑馬", "披薩", "一隻狗",
          "someone talking about sleep problems", "stock market news", "失眠", "股票下跌"]:
    v = e.query(q)
    line = f"{q:38s} " + " ".join(f"{x:5.2f}" for x in imgs @ v)
    if au is not None:
        line += "  " + " ".join(f"{x:5.2f}" for x in au @ v)
    print(line)
