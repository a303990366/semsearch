# 打包 SemSearch（CPU 版，任何 Windows x64 都能跑）
# 第一次先建打包用的環境：
#   uv venv ..\.venv-build --python 3.12
#   uv pip install --python ..\.venv-build\Scripts\python.exe torch torchvision --index-url https://download.pytorch.org/whl/cpu
#   uv pip install --python ..\.venv-build\Scripts\python.exe sentence-transformers==6.1.0 transformers==5.19.0 accelerate numpy pillow pillow-heif pymupdf python-docx av huggingface_hub PySide6 watchdog pyinstaller
Set-Location $PSScriptRoot
..\.venv-build\Scripts\python.exe make_icon.py
..\.venv-build\Scripts\pyinstaller SemSearch.spec --noconfirm --distpath dist --workpath build
Copy-Item 使用說明.txt dist\SemSearch\ -Force
if (Test-Path dist\SemSearch.zip) { Remove-Item dist\SemSearch.zip }
# tar -a 產生的 zip 幾乎沒壓縮（889MB），用 Python 的 deflate 可以壓到約 335MB
..\.venv-build\Scripts\python.exe -c "import shutil; shutil.make_archive('dist/SemSearch', 'zip', 'dist', 'SemSearch')"
Get-Item dist\SemSearch.zip | Select-Object Name, @{n='MB';e={[int]($_.Length/1MB)}}
