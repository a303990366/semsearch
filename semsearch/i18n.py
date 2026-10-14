"""介面文字：英文（預設）與繁體中文。用法：tr("key", name=value)。"""
from __future__ import annotations

LANGUAGES = {"en": "English", "zh-TW": "繁體中文"}
_lang = "en"


def set_language(lang: str):
    global _lang
    _lang = lang if lang in LANGUAGES else "en"


def current() -> str:
    return _lang


def tr(key: str, **kw) -> str:
    entry = STRINGS[key]
    text = entry.get(_lang) or entry["en"]
    return text.format(**kw) if kw else text


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return tr("dur_sec", n=max(sec, 1))
    if sec < 3600:
        return tr("dur_min", n=sec // 60)
    h, m = sec // 3600, sec % 3600 // 60
    if h < 48:
        return tr("dur_hm", h=h, m=m) if m else tr("dur_h", h=h)
    return tr("dur_dh", d=h // 24, h=h % 24)


def kind_label(kind: str) -> str:
    key = f"kind_{kind}"
    return tr(key) if key in STRINGS else kind


STRINGS: dict[str, dict[str, str]] = {
    # ---- 狀態列
    "model_loading": {"en": "Loading the model… (first run downloads about 1.5 GB)",
                      "zh-TW": "模型載入中…（第一次需要下載約 1.5GB）"},
    "model_failed": {"en": "Couldn't load the model: {e}", "zh-TW": "模型載入失敗：{e}"},
    "index_open_failed": {"en": "Couldn't open the index: {e}", "zh-TW": "索引檔開啟失敗：{e}"},
    "index_error": {"en": "Indexing error — see app.log", "zh-TW": "索引發生錯誤，詳見 app.log"},
    "no_folders": {"en": "No folders yet — click ⚙ at the bottom right to add some",
                   "zh-TW": "尚未設定資料夾 — 點右下角 ⚙ 加入"},
    "scanning": {"en": "Scanning files…", "zh-TW": "掃描檔案中…"},
    "progress": {"en": "Indexing {i}/{total} ({pct}%) · about {eta} left · {name}",
                 "zh-TW": "索引中 {i}/{total}（{pct}%）· 剩約 {eta} · {name}"},
    "status_indexed": {"en": "{n} files indexed", "zh-TW": "已索引 {n} 個檔案"},
    "status_indexed_run": {"en": "{n} files indexed (this run: {summary})",
                           "zh-TW": "已索引 {n} 個檔案（本次 {summary}）"},
    "model_still_loading": {"en": "The model is still loading; results will show up when it's ready…",
                            "zh-TW": "模型還在載入，載好後會自動顯示結果…"},

    # ---- 通知
    "notify_start_title": {"en": "Indexing started", "zh-TW": "開始建立索引"},
    "notify_start_body": {
        "en": "{total} files ({detail})\nEstimated time: {eta}. You'll get a notification when it's done.\n"
              "Text files go first, so you can search them soon.",
        "zh-TW": "共 {total} 個檔案（{detail}）\n預估 {eta}，完成後會再通知你。\n文字類會先處理，處理完就能先搜尋。"},
    "list_sep": {"en": ", ", "zh-TW": "、"},
    "summary": {"en": "Processed {total}: {ok} succeeded, {failed} failed",
                "zh-TW": "處理 {total} 份：成功 {ok}、失敗 {failed}"},
    "summary_skipped": {"en": ", {skipped} skipped", "zh-TW": "、略過 {skipped}"},
    "notify_done_title": {"en": "Indexing complete", "zh-TW": "索引完成"},
    "notify_done_body": {"en": "{summary}\nTook {took}. {n} files are now searchable.",
                         "zh-TW": "{summary}\n花費 {took}，目前可搜尋 {n} 個檔案。"},
    "notify_done_failed": {"en": "\nFailed files: right-click the tray icon → Open log",
                           "zh-TW": "\n失敗清單：系統匣右鍵 →「開啟記錄檔」"},
    "started_title": {"en": "SemSearch is running", "zh-TW": "SemSearch 已啟動"},
    "started_body": {"en": "Press {hotkey} to search", "zh-TW": "按 {hotkey} 開始搜尋"},
    "hotkey_fail_title": {"en": "Couldn't register the hotkey", "zh-TW": "快捷鍵無法註冊"},
    "hotkey_fail_body": {"en": "{hotkey} may be taken by another app. Pick a different one in Settings.",
                         "zh-TW": "{hotkey} 可能被其他程式佔用，請到設定換一組。"},
    "cannot_open": {"en": "Couldn't open the file", "zh-TW": "無法開啟"},

    # ---- 時間
    "dur_sec": {"en": "{n} sec", "zh-TW": "{n} 秒"},
    "dur_min": {"en": "{n} min", "zh-TW": "{n} 分鐘"},
    "dur_hm": {"en": "{h} h {m} min", "zh-TW": "{h} 小時 {m} 分"},
    "dur_h": {"en": "{h} h", "zh-TW": "{h} 小時"},
    "dur_dh": {"en": "{d} days {h} h", "zh-TW": "{d} 天 {h} 小時"},

    # ---- 檔案類型 / 位置
    "kind_text": {"en": "Text", "zh-TW": "文字"},
    "kind_pdf": {"en": "PDF", "zh-TW": "PDF"},
    "kind_docx": {"en": "Word", "zh-TW": "Word"},
    "kind_image": {"en": "Image", "zh-TW": "圖片"},
    "kind_audio": {"en": "Audio", "zh-TW": "音訊"},
    "kind_video": {"en": "Video", "zh-TW": "影片"},
    "page": {"en": "p. {n}", "zh-TW": "第 {n} 頁"},

    # ---- 搜尋框
    "placeholder": {"en": "Describe the file you're looking for…  e.g. a dog on the beach, the pet clause in my lease",
                    "zh-TW": "用自己的話描述要找的檔案…  例如：海灘上的狗、租約裡寵物的條款"},
    "key_hints": {"en": "Enter open · Ctrl+Enter show in folder · Esc close",
                  "zh-TW": "Enter 開啟 · Ctrl+Enter 所在位置 · Esc 關閉"},
    "btn_open": {"en": "Open", "zh-TW": "開啟"},
    "btn_reveal": {"en": "Show in folder", "zh-TW": "所在位置"},
    "settings_tip": {"en": "Settings", "zh-TW": "設定"},

    # ---- 設定
    "settings_title": {"en": "SemSearch Settings", "zh-TW": "SemSearch 設定"},
    "h_folders": {"en": "Folders to index (including subfolders)", "zh-TW": "要索引的資料夾（含子資料夾）"},
    "pick_folder": {"en": "Choose a folder to index", "zh-TW": "選擇要索引的資料夾"},
    "h_excludes": {"en": "Excluded folders", "zh-TW": "排除的資料夾"},
    "excludes_hint": {"en": "These folders and everything under them are skipped, e.g. code projects, backups, game installs.",
                      "zh-TW": "這些資料夾和底下的子資料夾都不索引，例如程式碼專案、備份、遊戲安裝檔。"},
    "pick_exclude": {"en": "Choose a folder to exclude", "zh-TW": "選擇要排除的資料夾"},
    "add_folder": {"en": "Add folder…", "zh-TW": "新增資料夾…"},
    "remove_selected": {"en": "Remove selected", "zh-TW": "移除選取"},
    "h_options": {"en": "Options", "zh-TW": "選項"},
    "opt_audio": {"en": "Index audio (mp3 / wav / m4a…)", "zh-TW": "索引音訊（mp3 / wav / m4a…）"},
    "opt_video": {"en": "Index video (one frame every 5 s + soundtrack; the slowest)",
                  "zh-TW": "索引影片（每 5 秒一張畫面 + 音軌，最耗時）"},
    "opt_autostart": {"en": "Start with Windows", "zh-TW": "開機時自動啟動"},
    "language": {"en": "Language:", "zh-TW": "語言："},
    "hotkey_label": {"en": "Hotkey to open search:", "zh-TW": "叫出搜尋框的快捷鍵："},
    "hotkey_placeholder": {"en": "e.g. ctrl+alt+space, alt+shift+f", "zh-TW": "例如 ctrl+alt+space、alt+shift+f"},
    "stats": {"en": "Index: {ok} files searchable, {bad} couldn't be processed  ·  {status}",
              "zh-TW": "目前索引：可搜尋 {ok} 個檔案，無法處理 {bad} 個　·　{status}"},
    "save": {"en": "Save", "zh-TW": "儲存"},
    "cancel": {"en": "Cancel", "zh-TW": "取消"},

    # ---- 系統匣選單
    "menu_search": {"en": "Search", "zh-TW": "搜尋"},
    "menu_settings": {"en": "Settings…", "zh-TW": "設定…"},
    "menu_rescan": {"en": "Rescan now", "zh-TW": "立即重新掃描"},
    "menu_log": {"en": "Open log", "zh-TW": "開啟記錄檔"},
    "menu_quit": {"en": "Quit", "zh-TW": "結束"},
}
