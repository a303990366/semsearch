"""雙擊啟動桌面助手。若不是用專案 .venv 的 Python 開的，就轉交給 .venv\\Scripts\\pythonw.exe。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYW = ROOT / ".venv" / "Scripts" / "pythonw.exe"

if VENV_PYW.exists() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
    subprocess.Popen([str(VENV_PYW), str(Path(__file__).resolve())], cwd=ROOT)
    sys.exit(0)

sys.path.insert(0, str(ROOT))
from semsearch.app import main  # noqa: E402

main()
