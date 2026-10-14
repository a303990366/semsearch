"""桌面助手：系統匣常駐 + 全域快捷鍵叫出搜尋框 + 背景索引設定好的資料夾。

結構：
  主執行緒（Qt UI） ── SearchThread（查詢）
                    └─ IndexerThread（載模型、掃描、索引；查詢時讓路）
                    └─ HotkeyThread（Win32 RegisterHotKey）
                    └─ watchdog（檔案變動 → 5 秒後重新掃描）
"""
from __future__ import annotations

import ctypes
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections import Counter
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QFileInfo, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QColor, QCursor, QFont, QIcon, QImageReader, QPainter, QPalette, QPen, QPixmap,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFileIconProvider, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QSizePolicy, QSystemTrayIcon,
    QToolButton,
    QVBoxLayout, QWidget,
)

from . import config
from .settings import Settings

log = logging.getLogger("semsearch")
INSTANCE_KEY = "semsearch-desktop-assistant"
RESCAN_EVERY_SEC = 30 * 60
WATCH_DEBOUNCE_MS = 5000
BIG_RUN = 20             # 一次要處理這麼多檔案以上才跳通知
PROGRESS_LOG_EVERY = 25
# 各類型每單位秒數的經驗值（還沒實測前用來估剩餘時間；影音的 1 單位 = 10MB）
DEFAULT_SEC_CPU = {"text": 0.3, "docx": 0.3, "pdf": 1.5, "image": 4.0, "audio": 10.0, "video": 40.0}
DEFAULT_SEC_GPU = {"text": 0.05, "docx": 0.05, "pdf": 0.3, "image": 0.2, "audio": 1.5, "video": 4.0}
REL_CUTOFF = 0.08      # 比第一名低超過這麼多分的結果不顯示
VLC = Path(r"C:\Program Files\VideoLAN\VLC\vlc.exe")


# ---------------------------------------------------------------- 背景執行緒

class Bridge(QObject):
    status = Signal(str)
    model_ready = Signal()
    results = Signal(int, object)
    hotkey = Signal()
    fs_changed = Signal()
    notify = Signal(str, str)


class IndexerThread(threading.Thread):
    def __init__(self, bridge: Bridge, get_settings):
        super().__init__(daemon=True, name="indexer")
        self.bridge = bridge
        self.get_settings = get_settings
        self.trigger = threading.Event()
        self.restart = threading.Event()
        self.ready = threading.Event()
        self.emb = None
        self.announce = True        # 啟動、改設定、手動重掃時一定通知；檔案監看觸發的小量更新不吵人
        self.kind_sec: dict[str, float] = {}   # 各類型實測平均秒數（估剩餘時間用）

    def rescan(self, restart: bool = False):
        if restart:
            self.restart.set()
            self.announce = True
        self.trigger.set()

    def run(self):
        self.bridge.status.emit("模型載入中…（第一次需要下載約 1.5GB）")
        try:
            from .embedder import Embedder
            self.emb = Embedder()
        except Exception as e:
            log.exception("model load failed")
            self.bridge.status.emit(f"模型載入失敗：{e}")
            return
        self.ready.set()
        self.bridge.model_ready.emit()

        from .store import Store
        try:
            store = Store()
        except Exception as e:
            log.exception("open index failed")
            self.bridge.status.emit(f"索引檔開啟失敗：{e}")
            return
        self.trigger.set()
        while True:
            self.trigger.wait(timeout=RESCAN_EVERY_SEC)
            self.trigger.clear()
            self.restart.clear()
            try:
                self._run_once(store)
            except Exception:
                log.exception("index pass failed")
                self.bridge.status.emit("索引發生錯誤，詳見 app.log")

    def _run_once(self, store):
        from .indexer import index_one, plan
        s = self.get_settings()
        announce, self.announce = self.announce, False
        if not s.folders:
            self.bridge.status.emit("尚未設定資料夾 — 點右下角 ⚙ 加入")
            return
        self.bridge.status.emit("掃描檔案中…")
        todo, removed = plan(store, s.roots, s.skip_kinds, prune_all=True, excludes=s.excludes)
        # 暫時不存在的資料夾（例如外接硬碟沒插）不要清掉它的索引
        missing = [f.rstrip("\\/") + "\\" for f in s.folders if not Path(f).is_dir()]
        removed = [p for p in removed if not any(p.startswith(m) for m in missing)]
        for sp in removed:
            store.delete_file(sp)
        store.commit()
        announce = announce or len(todo) >= BIG_RUN
        # 剩餘工作量（以「單位」計：一般檔案 1 單位，影音每 10MB 1 單位），逐檔扣掉
        left = Counter()
        for j in todo:
            left[j.kind] += _units(j)
        if todo and announce:
            kinds = Counter(KIND_LABEL.get(j.kind, j.kind) for j in todo)
            detail = "、".join(f"{k} {n:,}" for k, n in kinds.most_common())
            eta = self._eta(left)
            self.bridge.notify.emit(
                "開始建立索引",
                f"共 {len(todo):,} 個檔案（{detail}）\n預估 {fmt_duration(eta)}，完成後會再通知你。"
                "\n文字類會先處理，處理完就能先搜尋。")
            log.info("index start: %d files (%s), eta %s", len(todo), detail, fmt_duration(eta))

        t0 = time.time()
        ok = failed = skipped = 0
        for i, job in enumerate(todo, 1):
            if self.restart.is_set():
                log.info("index interrupted at %d/%d (settings changed)", i - 1, len(todo))
                self.trigger.set()
                return
            remaining = self._eta(left)
            left[job.kind] -= _units(job)
            self.bridge.status.emit(
                f"索引中 {i:,}/{len(todo):,}（{(i - 1) * 100 // len(todo)}%）· 剩約 {fmt_duration(remaining)}"
                f" · {job.path.name}")
            t = time.time()
            n, err, was_skipped = index_one(store, self.emb, job)
            self._learn(job.kind, (time.time() - t) / _units(job))
            if was_skipped:
                skipped += 1
                log.info("skipped: %s: %s", job.path, err)
            elif err:
                failed += 1
                log.warning("index failed: %s: %s", job.path, err)
            else:
                ok += 1
            if i % 10 == 0:
                store.commit()
            if i % PROGRESS_LOG_EVERY == 0:
                log.info("progress %d/%d (ok %d, failed %d, skipped %d), remaining ~%s",
                         i, len(todo), ok, failed, skipped, fmt_duration(remaining))
        store.commit()
        n_files = store.db.execute("SELECT COUNT(*) FROM files WHERE error IS NULL").fetchone()[0]
        took = time.time() - t0
        if todo:
            summary = f"處理 {len(todo):,} 份：成功 {ok:,}、失敗 {failed:,}" + (f"、略過 {skipped:,}" if skipped else "")
            log.info("index done in %s: %s; removed %d", fmt_duration(took), summary, len(removed))
            if announce or failed:
                self.bridge.notify.emit(
                    "索引完成",
                    f"{summary}\n花費 {fmt_duration(took)}，目前可搜尋 {n_files:,} 個檔案。"
                    + ("\n失敗清單：系統匣右鍵 →「開啟記錄檔」" if failed else ""))
            self.bridge.status.emit(f"已索引 {n_files:,} 個檔案（本次 {summary}）")
        else:
            self.bridge.status.emit(f"已索引 {n_files:,} 個檔案")

    # 估時：先用各類型的經驗值，跑過之後換成實測平均
    def _learn(self, kind: str, sec: float):
        old = self.kind_sec.get(kind)
        self.kind_sec[kind] = sec if old is None else old * 0.9 + sec * 0.1

    def _eta(self, left: Counter) -> float:
        default = DEFAULT_SEC_GPU if self.emb and self.emb.device == "cuda" else DEFAULT_SEC_CPU
        return sum(max(units, 0) * self.kind_sec.get(kind, default.get(kind, 1.0))
                   for kind, units in left.items())


def _units(job) -> float:
    """影音耗時跟長度成正比，用檔案大小粗估（每 10MB 算 1 單位）；其他檔案 1 單位。"""
    return max(1.0, job.size / 10e6) if job.kind in ("video", "audio") else 1.0


class SearchThread(threading.Thread):
    def __init__(self, bridge: Bridge, indexer: IndexerThread, get_settings):
        super().__init__(daemon=True, name="search")
        self.bridge = bridge
        self.indexer = indexer
        self.get_settings = get_settings
        self.q: queue.Queue = queue.Queue()

    def submit(self, qid: int, text: str):
        self.q.put((qid, text))

    def run(self):
        self.indexer.ready.wait()
        from .search import search
        from .store import Store
        store = Store()
        while True:
            item = self.q.get()
            while not self.q.empty():          # 只處理最新的一次輸入
                item = self.q.get_nowait()
            qid, text = item
            try:
                res = search(store, self.indexer.emb, text, self.get_settings().max_results,
                             rel_cutoff=REL_CUTOFF)
            except Exception:
                log.exception("search failed")
                res = []
            self.bridge.results.emit(qid, res)


MOD = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012


def parse_hotkey(combo: str) -> tuple[int, int] | None:
    mods, vk = 0, None
    for part in combo.lower().replace(" ", "").split("+"):
        if part in MOD:
            mods |= MOD[part]
        elif part == "space":
            vk = 0x20
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            vk = 0x6F + int(part[1:])
        else:
            return None
    return (mods, vk) if vk and mods else None


class HotkeyThread(threading.Thread):
    def __init__(self, combo: str, on_press):
        super().__init__(daemon=True, name="hotkey")
        self.combo, self.on_press = combo, on_press
        self.ok = False
        self.started_evt = threading.Event()
        self.tid = 0

    def run(self):
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self.tid = kernel32.GetCurrentThreadId()
        parsed = parse_hotkey(self.combo)
        self.ok = bool(parsed) and bool(user32.RegisterHotKey(None, 1, parsed[0] | MOD_NOREPEAT, parsed[1]))
        self.started_evt.set()
        if not self.ok:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.on_press()
        user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self.tid:
            ctypes.windll.user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)


def _force_foreground(hwnd: int):
    """Windows 不讓背景程式搶焦點；暫時把輸入佇列掛到目前前景視窗的執行緒上再切換。"""
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    fg_tid = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_tid) and fg_tid != me and user32.AttachThreadInput(fg_tid, me, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(fg_tid, me, False)


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    if sec < 60:
        return f"{max(sec, 1)} 秒"
    if sec < 3600:
        return f"{sec // 60} 分鐘"
    h, m = sec // 3600, sec % 3600 // 60
    if h < 48:
        return f"{h} 小時 {m} 分" if m else f"{h} 小時"
    return f"{h // 24} 天 {h % 24} 小時"


# ---------------------------------------------------------------- 開檔

def open_file(r):
    """直接開檔；影音有時間碼且裝了 VLC 時，跳到命中的那一刻。"""
    if "t" in r.locator and r.kind in ("video", "audio") and VLC.exists():
        subprocess.Popen([str(VLC), f"--start-time={int(r.locator['t'])}", r.path])
    else:
        os.startfile(r.path)


def reveal_in_explorer(path: str):
    subprocess.Popen(f'explorer /select,"{path}"')


# ---------------------------------------------------------------- UI

STYLE = """
QWidget#panel { background: #1f2023; border: 1px solid #3a3b40; border-radius: 12px; }
QLineEdit { background: #2a2b30; color: #f2f2f2; border: none; border-radius: 8px; padding: 10px 14px;
            font-size: 18px; selection-background-color: #4c6ef5; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget::item { border-radius: 8px; }
QListWidget::item:selected { background: #2f3b5c; }
QListWidget::item:hover:!selected { background: #2a2b30; }
QLabel { color: #e6e6e6; }
QLabel#name { font-size: 14px; font-weight: 600; }
QLabel#path { color: #8b8d95; font-size: 11px; }
QLabel#snippet { color: #b5b7bf; font-size: 12px; }
QLabel#badge { color: #9fb3ff; background: #263052; border-radius: 4px; padding: 1px 6px; font-size: 11px; }
QLabel#status { color: #8b8d95; font-size: 11px; }
QPushButton { background: #2f3036; color: #e6e6e6; border: none; border-radius: 6px; padding: 5px 10px; }
QPushButton:hover { background: #3d4fa3; }
QToolButton { background: transparent; color: #8b8d95; border: none; font-size: 15px; }
QToolButton:hover { color: #ffffff; }

QDialog#settings { background: #1f2023; }
QLabel#heading { color: #ffffff; font-size: 13px; font-weight: 600; padding-top: 6px; }
QLabel#hint { color: #9a9ca5; font-size: 11px; }
QListWidget#folders { background: #2a2b30; border: 1px solid #3a3b40; border-radius: 6px; color: #e6e6e6;
                      padding: 4px; }
QListWidget#folders::item { padding: 4px 6px; border-radius: 4px; }
QListWidget#folders::item:selected { background: #3d4fa3; color: #ffffff; }
QLineEdit#field { font-size: 13px; padding: 6px 10px; border: 1px solid #3a3b40; border-radius: 6px; }
QCheckBox { color: #e6e6e6; spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #5a5c66; border-radius: 3px;
                       background: #2a2b30; }
QCheckBox::indicator:checked { background: #4c6ef5; border-color: #4c6ef5; }
QDialogButtonBox QPushButton { min-width: 72px; padding: 6px 14px; }
QMenu { background: #26272b; color: #e6e6e6; border: 1px solid #3a3b40; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 4px; }
QMenu::item:selected { background: #3d4fa3; }
QMenu::separator { height: 1px; background: #3a3b40; margin: 4px 8px; }
QToolTip { background: #26272b; color: #e6e6e6; border: 1px solid #3a3b40; }
QScrollBar:vertical { background: transparent; width: 8px; }
QScrollBar::handle:vertical { background: #44464d; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""


def dark_palette() -> QPalette:
    """原生對話框（選資料夾以外）與 Fusion 元件都用深色，避免白底配淺色字看不清楚。"""
    pal = QPalette()
    for role, color in [
        (QPalette.Window, "#1f2023"), (QPalette.WindowText, "#e6e6e6"),
        (QPalette.Base, "#2a2b30"), (QPalette.AlternateBase, "#26272b"),
        (QPalette.Text, "#e6e6e6"), (QPalette.Button, "#2f3036"), (QPalette.ButtonText, "#e6e6e6"),
        (QPalette.Highlight, "#3d4fa3"), (QPalette.HighlightedText, "#ffffff"),
        (QPalette.ToolTipBase, "#26272b"), (QPalette.ToolTipText, "#e6e6e6"),
        (QPalette.PlaceholderText, "#7d7f88"), (QPalette.Link, "#9fb3ff"),
    ]:
        pal.setColor(role, QColor(color))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#6b6d75"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#6b6d75"))
    return pal

KIND_LABEL = {"text": "文字", "pdf": "PDF", "docx": "Word", "image": "圖片", "audio": "音訊", "video": "影片"}


def make_app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#4c6ef5"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 14, 14)
    p.setPen(QPen(QColor("white"), 6, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(14, 12, 26, 26)
    p.drawLine(36, 35, 49, 49)
    p.end()
    return QIcon(pm)


def _shrinkable(label: QLabel):
    """長路徑/摘要不撐寬整列，否則右邊的按鈕會被擠出畫面。"""
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setMinimumWidth(0)


class ResultRow(QWidget):
    def __init__(self, r, thumb: QPixmap, on_open, on_reveal):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        icon = QLabel()
        icon.setFixedSize(52, 52)
        icon.setAlignment(Qt.AlignCenter)
        icon.setPixmap(thumb)
        lay.addWidget(icon)

        mid = QVBoxLayout()
        mid.setSpacing(2)
        top = QHBoxLayout()
        name = QLabel(Path(r.path).name)
        name.setObjectName("name")
        top.addWidget(name)
        badge_text = KIND_LABEL.get(r.kind, r.kind) + (f" · {r.where}" if r.where else "")
        badge = QLabel(badge_text)
        badge.setObjectName("badge")
        top.addWidget(badge)
        top.addStretch()
        mid.addLayout(top)
        path = QLabel(str(Path(r.path).parent))
        path.setObjectName("path")
        path.setToolTip(r.path)
        _shrinkable(path)
        mid.addWidget(path)
        if r.modality == "text" and r.snippet:
            s = " ".join(r.snippet.split())
            sn = QLabel(s[:140] + ("…" if len(s) > 140 else ""))
            sn.setObjectName("snippet")
            _shrinkable(sn)
            mid.addWidget(sn)
        lay.addLayout(mid, 1)

        b_open = QPushButton("開啟")
        b_open.clicked.connect(on_open)
        b_dir = QPushButton("所在位置")
        b_dir.clicked.connect(on_reveal)
        lay.addWidget(b_open)
        lay.addWidget(b_dir)


class SearchWindow(QWidget):
    def __init__(self, ctrl: "Controller"):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.ctrl = ctrl
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("SemSearch")
        self.resize(760, 560)
        self.results = []
        self.qid = 0
        self.icons = QFileIconProvider()
        self.thumb_cache: dict[str, QPixmap] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QWidget()
        panel.setObjectName("panel")
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 12, 12, 8)

        self.input = QLineEdit()
        self.input.setPlaceholderText("用自己的話描述要找的檔案…  例如：海灘上的狗、租約裡寵物的條款")
        self.input.textChanged.connect(self._on_text)
        self.input.installEventFilter(self)
        lay.addWidget(self.input)

        self.list = QListWidget()
        self.list.itemActivated.connect(lambda _: self.open_current())
        self.list.itemDoubleClicked.connect(lambda _: self.open_current())
        lay.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        self.status = QLabel("")
        self.status.setObjectName("status")
        bottom.addWidget(self.status, 1)
        hint = QLabel("Enter 開啟 · Ctrl+Enter 所在位置 · Esc 關閉")
        hint.setObjectName("status")
        bottom.addWidget(hint)
        gear = QToolButton()
        gear.setText("⚙")
        gear.setToolTip("設定")
        gear.clicked.connect(ctrl.open_settings)
        bottom.addWidget(gear)
        lay.addLayout(bottom)

        self.debounce = QTimer(self, singleShot=True, interval=250)
        self.debounce.timeout.connect(self._submit)

    # -- 顯示 / 隱藏
    def toggle(self):
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.summon()

    def summon(self):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(g.x() + (g.width() - self.width()) // 2, g.y() + g.height() // 6)
        self.show()
        self.raise_()
        self.activateWindow()
        _force_foreground(int(self.winId()))
        self.input.setFocus()
        self.input.selectAll()

    def changeEvent(self, e):
        if e.type() == e.Type.ActivationChange and not self.isActiveWindow() and not self.ctrl.dialog_open:
            QTimer.singleShot(150, lambda: (not self.isActiveWindow()) and self.hide())
        super().changeEvent(e)

    # -- 鍵盤
    def eventFilter(self, obj, e):
        if obj is self.input and e.type() == e.Type.KeyPress:
            k, mods = e.key(), e.modifiers()
            if k == Qt.Key_Escape:
                self.hide()
                return True
            if k in (Qt.Key_Down, Qt.Key_Up) and self.list.count():
                row = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                if mods & Qt.ControlModifier:
                    self.reveal_current()
                else:
                    self.open_current()
                return True
        return super().eventFilter(obj, e)

    # -- 查詢
    def _on_text(self, _):
        self.debounce.start()

    def _submit(self):
        text = self.input.text().strip()
        self.qid += 1
        if not text:
            self.results = []
            self.list.clear()
            return
        if not self.ctrl.indexer.ready.is_set():
            self.status.setText("模型還在載入，載好後會自動顯示結果…")
        self.ctrl.searcher.submit(self.qid, text)

    def show_results(self, qid: int, results: list):
        if qid != self.qid:
            return                       # 過期的查詢
        self.results = results
        self.list.clear()
        for idx, r in enumerate(results):
            item = QListWidgetItem()
            row = ResultRow(r, self._thumb(r.path, r.kind),
                            lambda _=False, i=idx: self.open_index(i),
                            lambda _=False, i=idx: self.reveal_index(i))
            item.setSizeHint(row.sizeHint() + QSize(0, 4))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        if results:
            self.list.setCurrentRow(0)

    def _thumb(self, path: str, kind: str) -> QPixmap:
        if path in self.thumb_cache:
            return self.thumb_cache[path]
        pm = QPixmap()
        if kind == "image":
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                reader.setScaledSize(size.scaled(52, 52, Qt.KeepAspectRatio))
                img = reader.read()
                if not img.isNull():
                    pm = QPixmap.fromImage(img)
        if pm.isNull():
            pm = self.icons.icon(QFileInfo(path)).pixmap(36, 36)
        self.thumb_cache[path] = pm
        return pm

    # -- 開檔
    def open_current(self):
        self.open_index(max(0, self.list.currentRow()))

    def reveal_current(self):
        self.reveal_index(max(0, self.list.currentRow()))

    def open_index(self, i: int):
        if 0 <= i < len(self.results):
            self.hide()
            try:
                open_file(self.results[i])
            except OSError as e:
                self.ctrl.tray.showMessage("無法開啟", str(e))

    def reveal_index(self, i: int):
        if 0 <= i < len(self.results):
            self.hide()
            reveal_in_explorer(self.results[i].path)


class FolderList(QWidget):
    """資料夾清單 + 新增 / 移除按鈕。"""

    def __init__(self, folders: list[str], pick_title: str):
        super().__init__()
        self.pick_title = pick_title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setObjectName("folders")
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.addItems(folders)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton("新增資料夾…")
        add.clicked.connect(self._add)
        rm = QPushButton("移除選取")
        rm.clicked.connect(lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        row.addWidget(add)
        row.addWidget(rm)
        row.addStretch()
        lay.addLayout(row)

    def _add(self):
        d = QFileDialog.getExistingDirectory(self, self.pick_title)
        if d:
            d = str(Path(d).resolve())
            if d not in self.folders():
                self.list.addItem(d)

    def folders(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]


class SettingsDialog(QDialog):
    def __init__(self, s: Settings, stats_text: str = ""):
        super().__init__(None, Qt.WindowStaysOnTopHint)
        self.setObjectName("settings")
        self.setWindowTitle("SemSearch 設定")
        self.setWindowIcon(make_app_icon())
        self.resize(620, 600)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        lay.addWidget(_heading("要索引的資料夾（含子資料夾）"))
        self.folders = FolderList(s.folders, "選擇要索引的資料夾")
        lay.addWidget(self.folders, 3)

        lay.addWidget(_heading("排除的資料夾"))
        hint = QLabel("這些資料夾和底下的子資料夾都不索引，例如程式碼專案、備份、遊戲安裝檔。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.excludes = FolderList(s.excludes, "選擇要排除的資料夾")
        lay.addWidget(self.excludes, 2)

        lay.addWidget(_heading("選項"))
        self.audio = QCheckBox("索引音訊（mp3 / wav / m4a…）")
        self.audio.setChecked(s.index_audio)
        self.video = QCheckBox("索引影片（每 5 秒一張畫面 + 音軌，最耗時）")
        self.video.setChecked(s.index_video)
        self.autostart = QCheckBox("開機時自動啟動")
        self.autostart.setChecked(s.autostart)
        for w in (self.audio, self.video, self.autostart):
            lay.addWidget(w)

        hk = QHBoxLayout()
        hk.addWidget(QLabel("叫出搜尋框的快捷鍵："))
        self.hotkey = QLineEdit(s.hotkey)
        self.hotkey.setObjectName("field")
        self.hotkey.setPlaceholderText("例如 ctrl+alt+space、alt+shift+f")
        hk.addWidget(self.hotkey, 1)
        lay.addLayout(hk)

        if stats_text:
            st = QLabel(stats_text)
            st.setObjectName("hint")
            st.setWordWrap(True)
            lay.addWidget(st)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("儲存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def _accept(self):
        if not parse_hotkey(self.hotkey.text()):
            self.hotkey.setStyleSheet("border: 1px solid #e03131;")
            return
        self.accept()

    def result_settings(self, old: Settings) -> Settings:
        return Settings(
            folders=self.folders.folders(),
            excludes=self.excludes.folders(),
            hotkey=self.hotkey.text().strip().lower(),
            index_audio=self.audio.isChecked(),
            index_video=self.video.isChecked(),
            autostart=self.autostart.isChecked(),
            max_results=old.max_results,
        )


def _heading(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("heading")
    return lb


# ---------------------------------------------------------------- 控制器

class Controller:
    def __init__(self, app: QApplication):
        self.app = app
        self.settings = Settings.load()
        self.dialog_open = False
        self.bridge = Bridge()
        self.indexer = IndexerThread(self.bridge, lambda: self.settings)
        self.searcher = SearchThread(self.bridge, self.indexer, lambda: self.settings)
        self.window = SearchWindow(self)
        self.hotkey_thread: HotkeyThread | None = None
        self.observer = None

        self.watch_debounce = QTimer(singleShot=True, interval=WATCH_DEBOUNCE_MS)
        self.watch_debounce.timeout.connect(lambda: self.indexer.rescan())

        self.bridge.status.connect(self._on_status)
        self.bridge.results.connect(self.window.show_results)
        self.bridge.hotkey.connect(self.window.toggle)
        self.bridge.fs_changed.connect(self.watch_debounce.start)
        self.bridge.notify.connect(lambda title, msg: self.tray.showMessage(
            title, msg, QSystemTrayIcon.Information, 15000))

        self.tray = QSystemTrayIcon(make_app_icon())
        menu = QMenu()
        self.act_search = QAction("搜尋")
        self.act_search.triggered.connect(self.window.summon)
        act_settings = QAction("設定…")
        act_settings.triggered.connect(self.open_settings)
        act_rescan = QAction("立即重新掃描")
        act_rescan.triggered.connect(lambda: self.indexer.rescan(restart=True))
        act_log = QAction("開啟記錄檔")
        act_log.triggered.connect(lambda: os.startfile(config.DATA_DIR / "app.log"))
        act_quit = QAction("結束")
        act_quit.triggered.connect(self.quit)
        self._actions = [self.act_search, act_settings, act_rescan, act_log, act_quit]
        for a in self._actions[:-1]:
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction(act_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: reason == QSystemTrayIcon.Trigger and self.window.toggle())
        self.tray.show()

        self.indexer.start()
        self.searcher.start()
        self._apply_hotkey()
        self._apply_watchers()

        if not self.settings.folders:
            QTimer.singleShot(300, self.open_settings)
        else:
            self.tray.showMessage("SemSearch 已啟動", f"按 {self.settings.hotkey} 開始搜尋")

    def _on_status(self, text: str):
        if not text.startswith("索引中"):
            log.info("status: %s", text)
        self.window.status.setText(text)
        self.tray.setToolTip(f"SemSearch — {text}"[:120])

    def _apply_hotkey(self):
        if self.hotkey_thread:
            self.hotkey_thread.stop()
        self.hotkey_thread = HotkeyThread(self.settings.hotkey, self.bridge.hotkey.emit)
        self.hotkey_thread.start()
        self.hotkey_thread.started_evt.wait(2)
        self.act_search.setText(f"搜尋\t{self.settings.hotkey}")
        if not self.hotkey_thread.ok:
            self.tray.showMessage("快捷鍵無法註冊",
                                  f"{self.settings.hotkey} 可能被其他程式佔用，請到設定換一組。")

    def _apply_watchers(self):
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
        if self.observer:
            self.observer.stop()
        bridge = self.bridge
        supported = (config.TEXT_EXT | config.PDF_EXT | config.DOCX_EXT | config.IMAGE_EXT
                     | config.AUDIO_EXT | config.VIDEO_EXT)

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.event_type in ("opened", "closed", "closed_no_write"):
                    return
                paths = [event.src_path, getattr(event, "dest_path", "")]
                if event.is_directory or any(Path(p).suffix.lower() in supported for p in paths if p):
                    bridge.fs_changed.emit()

        self.observer = Observer()
        for root in self.settings.roots:
            try:
                self.observer.schedule(Handler(), str(root), recursive=True)
            except OSError:
                log.warning("cannot watch %s", root)
        self.observer.daemon = True
        self.observer.start()

    def _stats_text(self) -> str:
        import sqlite3
        try:
            db = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True, timeout=2)
            ok, bad = db.execute("SELECT SUM(error IS NULL), SUM(error IS NOT NULL) FROM files").fetchone()
            db.close()
        except sqlite3.Error:
            return ""
        return f"目前索引：可搜尋 {ok or 0:,} 個檔案，無法處理 {bad or 0:,} 個　·　{self.window.status.text()}"

    def open_settings(self):
        self.window.hide()
        self.dialog_open = True
        dlg = SettingsDialog(self.settings, self._stats_text())
        try:
            if dlg.exec() != QDialog.Accepted:
                return
            new = dlg.result_settings(self.settings)
            changed_index = (new.folders != self.settings.folders
                             or new.excludes != self.settings.excludes
                             or new.skip_kinds != self.settings.skip_kinds)
            changed_hotkey = new.hotkey != self.settings.hotkey
            self.settings = new
            new.save()
            if changed_hotkey:
                self._apply_hotkey()
            if changed_index:
                self._apply_watchers()
                self.indexer.rescan(restart=True)
        finally:
            self.dialog_open = False

    def quit(self):
        if self.hotkey_thread:
            self.hotkey_thread.stop()
        if self.observer:
            self.observer.stop()
        self.tray.hide()
        self.app.quit()
        os._exit(0)            # 背景 CUDA 執行緒不用等


def _setup_logging():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logfile = config.DATA_DIR / "app.log"
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(logfile, encoding="utf-8")],
    )
    for noisy in ("httpx", "httpcore", "urllib3", "huggingface_hub", "sentence_transformers", "transformers"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # pythonw 沒有 console，stdout/stderr 是 None，函式庫一寫就會崩
    if sys.stdout is None or sys.stderr is None:
        f = open(logfile, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")


def main():
    _setup_logging()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("SemSearch")
    app.setWindowIcon(make_app_icon())
    app.setFont(QFont("Microsoft JhengHei UI", 10))
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(STYLE)

    # 單一實例：已在執行就叫它顯示搜尋框
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return
    QLocalServer.removeServer(INSTANCE_KEY)
    server = QLocalServer()
    server.listen(INSTANCE_KEY)

    ctrl = Controller(app)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), ctrl.window.summon()))
    log.info("started; folders=%s", ctrl.settings.folders)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
