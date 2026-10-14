# -*- mode: python ; coding: utf-8 -*-
# 打包：.venv-build\Scripts\pyinstaller packaging\SemSearch.spec --noconfirm
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

hidden = (
    collect_submodules("sentence_transformers")
    + collect_submodules("transformers.models.embedding_gemma2")
    + collect_submodules("transformers.models.gemma4")
    + collect_submodules("transformers.models.auto")
)
datas = collect_data_files("transformers") + collect_data_files("sentence_transformers")
# transformers 會用 importlib.metadata 檢查這些套件的版本
for pkg in ["transformers", "tokenizers", "huggingface_hub", "safetensors", "accelerate", "torch",
            "torchvision", "numpy", "tqdm", "regex", "requests", "packaging", "filelock", "pyyaml",
            "sentence-transformers", "pillow", "scikit-learn", "scipy", "av"]:
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# torchvision 0.29 的原生擴充改名為 *_stable.pyd，PyInstaller 內建 hook 抓不到
import torchvision, glob, os
tv_dir = os.path.dirname(torchvision.__file__)
binaries = [(f, "torchvision") for f in glob.glob(os.path.join(tv_dir, "*.pyd"))]

a = Analysis(
    ["entry.py"],
    pathex=[".."],
    hiddenimports=hidden,
    binaries=binaries,
    datas=datas,
    excludes=["librosa", "numba", "llvmlite", "matplotlib", "tkinter", "IPython", "jupyter",
              "pandas", "tensorflow", "jax", "flax", "onnxruntime", "winrt", "torch.utils.tensorboard"],
    noarchive=False,
    # transformers 會用 inspect 讀原始碼（docstring 處理、torch.compile 檢查），只有 .pyc 會壞
    module_collection_mode={"transformers": "pyz+py", "sentence_transformers": "pyz+py"},
)
# MSVC 執行階段：各套件各帶一份不同版本，PyInstaller 可能挑到舊的（14.42）放在根目錄；
# 舊版先被載入後，Qt 需要的新符號就找不到（DLL load failed while importing QtCore）。
# 根目錄的執行階段一律換成 PySide6 自帶的那一組（同一版、彼此相容、且一定滿足 Qt）。
import PySide6
_qt_dir = os.path.dirname(PySide6.__file__)
_qt_runtime = {os.path.basename(f).lower(): f for f in glob.glob(os.path.join(_qt_dir, "*.dll"))
               if os.path.basename(f).lower().startswith(("msvcp140", "vcruntime140", "concrt140"))}
a.binaries = [(dest, _qt_runtime.get(os.path.basename(dest).lower(), src)
               if os.path.dirname(dest) in ("", ".") else src, typ)
              for dest, src, typ in a.binaries]

# 依打包時的 PATH 不同，PyInstaller 可能從其他程式資料夾撈進 icuuc.dll（ICU 73）、ucrtbase、api-ms-win-*。
# Qt 會改載到這個舊 ICU 而不是 Windows 內建的，結果 QtCore 載入失敗（找不到指定的程序）。
# 這些 Windows 10 以上都內建，一律不打包。
def _system_provided(dest):
    name = os.path.basename(dest).lower()
    return name.startswith(("icu", "api-ms-win-")) or name == "ucrtbase.dll"

a.binaries = [b for b in a.binaries if not (os.path.dirname(b[0]) in ("", ".") and _system_provided(b[0]))]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="SemSearch",
    icon="semsearch.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SemSearch", upx=False)
