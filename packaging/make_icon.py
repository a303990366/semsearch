"""用 app 內建的圖示畫一個 .ico 給 exe 用。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication  # noqa: E402

from semsearch.app import make_app_icon  # noqa: E402

app = QApplication([])
out = Path(__file__).with_name("semsearch.ico")
make_app_icon().pixmap(64, 64).save(str(out), "ICO")
print(out)
