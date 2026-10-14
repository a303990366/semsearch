"""桌面助手的使用者設定，存在 ~/.semsearch/settings.json。"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config

SETTINGS_PATH = config.DATA_DIR / "settings.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "SemSearch"


@dataclass
class Settings:
    folders: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)   # 這些資料夾（含子資料夾）不索引
    hotkey: str = "ctrl+alt+space"
    index_audio: bool = True
    index_video: bool = True
    autostart: bool = False
    max_results: int = 12

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self):
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        apply_autostart(self.autostart)

    @property
    def skip_kinds(self) -> set[str]:
        skip = set()
        if not self.index_audio:
            skip.add("audio")
        if not self.index_video:
            skip.add("video")
        return skip

    @property
    def roots(self) -> list[Path]:
        return [Path(f) for f in self.folders if f and Path(f).is_dir()]


def apply_autostart(enabled: bool):
    """開機自動啟動：寫入 HKCU Run（用 pythonw 避免黑窗）。"""
    import winreg
    if getattr(sys, "frozen", False):          # 打包成 exe
        command = f'"{sys.executable}"'
    else:
        launcher = Path(__file__).resolve().parents[1] / "SemSearch.pyw"
        command = f'"{Path(sys.executable).with_name("pythonw.exe")}" "{launcher}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
