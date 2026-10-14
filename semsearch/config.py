import os
from pathlib import Path

# 預設用 unsloth 的鏡像（免 gated），可用環境變數換成 google/embeddinggemma-2
MODEL_ID = os.environ.get("SEMSEARCH_MODEL", "unsloth/embeddinggemma-2")

# 向量維度：768 / 512 / 256 / 128（Matryoshka 截斷）
DIM = int(os.environ.get("SEMSEARCH_DIM", "768"))

DATA_DIR = Path(os.environ.get("SEMSEARCH_HOME", Path.home() / ".semsearch"))
DB_PATH = DATA_DIR / "index.sqlite"
CACHE_DIR = DATA_DIR / "cache"

TEXT_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".json", ".yaml", ".yml", ".toml", ".ini", ".log",
    ".html", ".htm", ".xml",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".c", ".h", ".cpp", ".hpp",
    ".cs", ".rb", ".php", ".swift", ".sh", ".ps1", ".sql", ".vue", ".css",
}
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".wmv"}

SKIP_DIRS = {
    ".git", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".idea", ".vscode",
    "$RECYCLE.BIN", "System Volume Information", "AppData", ".cache", "dist", "build",
}

MAX_FILE_MB = 500
MAX_TEXT_MB = 2           # 超過的文字檔多半是 log / 資料匯出，索引價值低又很慢
TEXT_CHUNK_CHARS = 1200
TEXT_CHUNK_OVERLAP = 200
AUDIO_SEGMENT_SEC = 30      # 音訊每段長度（模型上限約 327 秒）
VIDEO_FRAME_EVERY_SEC = 5   # 影片每隔幾秒抽一張關鍵影格
VIDEO_MAX_FRAMES = 240
