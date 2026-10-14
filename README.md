# SemSearch

用自己的話搜尋電腦裡的檔案。照片、PDF、文件、程式碼、錄音、影片都能找，全部在本機執行，不會上傳任何檔案。

- 「海灘上的狗」→ 找到那張照片
- 「租約裡關於寵物的條款」→ 找到 PDF 的第 2 頁
- 「付款失敗的截圖」→ 找到錯誤畫面的截圖，截圖裡的文字不用 OCR 也認得
- 「影片裡有人在講失眠」→ 跳到影片的 00:30
- 中英文可以互搜

背後用的是 Google DeepMind 的 [EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2)（740M 參數，Apache 2.0）。它把文字、圖片、音訊放進同一個向量空間，所以用一句話就能找到意思相近的照片或錄音。

## 功能

- **桌面助手**：常駐在系統匣，按 `Ctrl+Alt+Space` 叫出搜尋框，邊打字邊出結果
- **直接開檔**：Enter 開啟檔案，Ctrl+Enter 在檔案總管中顯示；裝了 VLC 時，影音會跳到命中的時間點
- **多個資料夾**：可以設定要索引哪些資料夾，也可以排除子資料夾
- **自動更新**：資料夾裡的檔案新增、修改或刪除，約 5 秒後自動重新索引
- **定位到片段**：PDF 會顯示頁碼，影音會顯示時間碼
- **掃描版 PDF**：抽不到文字的頁面會整頁當成圖片交給模型
- **混合排序**：以語義相似度為主，關鍵字完全相符時額外加分

支援的格式：txt / md / 程式碼 / html、PDF、docx、jpg / png / heic / webp…、mp3 / wav / m4a…、mp4 / mov / mkv…

## 下載試用（Windows）

到 Releases 下載 `SemSearch.zip`，解壓後雙擊 `SemSearch.exe`。第一次啟動會下載模型，約 1.5GB。詳細步驟見 [packaging/使用說明.txt](packaging/使用說明.txt)。

打包版只用 CPU 計算，任何 Windows x64 電腦都能跑，但照片每張要 2 到 5 秒。要用 GPU 加速，請照下方說明從原始碼執行。

## 從原始碼執行

需要 Python 3.12。有 NVIDIA 顯示卡的話建議裝 CUDA 版 PyTorch。

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv\Scripts\python.exe -r requirements.txt

# 桌面助手
.venv\Scripts\pythonw.exe SemSearch.pyw

# 或用指令列
.venv\Scripts\python.exe -m semsearch index D:\Photos
.venv\Scripts\python.exe -m semsearch search "海灘上的狗"
```

在 RTX 4060 上的速度：文字每段 0.05 秒、照片每張 0.15 秒、30 秒音訊 0.15 秒、一次查詢約 0.3 秒。

## 架構

```
semsearch/
  app.py       桌面助手：系統匣、全域快捷鍵、搜尋框、設定、檔案監看、背景索引
  indexer.py   掃描資料夾，找出新增、變更、刪除的檔案（先處理文字，影片最後）
  extract.py   把檔案切成可嵌入的片段，記下頁碼或時間碼（用 Pillow 和 PyAV 在記憶體內解碼）
  embedder.py  EmbeddingGemma 2；查詢優先，背景索引會讓路
  store.py     SQLite：向量以 float16 存成 BLOB，另有 FTS5 全文索引
  search.py    以語義相似度排序，關鍵字命中加分，每個檔案只取最相關的一段
  ocr.py       Windows 內建 OCR（目前沒有啟用，模型本身已經讀得懂圖片裡的文字）
```

設定、索引和記錄檔放在 `~/.semsearch/`，模型放在 Hugging Face 的快取資料夾。

## 打包

```powershell
packaging\build.ps1
```

會產生 `packaging/dist/SemSearch/`（CPU 版）和 `SemSearch.zip`。第一次打包前要先建立打包環境，步驟寫在 build.ps1 開頭。

## 已知限制

- 目前只支援 Windows（全域快捷鍵、開機啟動、檔案總管整合都用到 Windows 的功能）
- PDF 只顯示頁碼，沒辦法直接跳到那一頁（各家 PDF 閱讀器的參數不一樣）
- 很多張長得很像的截圖，靠向量可能分不出差別，之後可能加回 OCR 做精確比對
- `testdata/` 裡沒有附上測試照片和影片（它們來自 Wikimedia Commons，授權要求標示作者），所以 `scripts/smoke_test.py` 需要你自己放幾張照片進去

## 授權

程式碼採用 [MIT](LICENSE) 授權。EmbeddingGemma 2 模型採用 Apache 2.0，第一次執行時會從 Hugging Face 下載，不包含在這個 repo 裡。
