SemSearch — find files on Windows by describing them
=====================================================

WHAT IT IS
Describe what you're looking for ("a dog on the beach", "the pet clause in my lease",
"screenshot of a payment error") and SemSearch finds matching photos, PDFs, documents,
recordings and videos in the folders you choose. Everything runs on your PC; nothing is uploaded.

REQUIREMENTS
- Windows 10 / 11 (64-bit)
- 8 GB RAM or more recommended (uses about 3.5 GB while running)
- About 3 GB of disk space (app 0.9 GB + AI model 1.5 GB + index)
- Internet on first launch only, to download the AI model (about 1.5 GB, once)

GETTING STARTED
1. Unzip the whole folder anywhere. Keep SemSearch.exe next to the _internal folder.
2. Double-click SemSearch.exe.
   If Windows shows "Windows protected your PC", click "More info" -> "Run anyway"
   (this preview build isn't code-signed).
3. The Settings window opens: click "Add folder…", pick the folders to search, then Save.
4. A blue magnifier icon appears in the system tray. Hover over it to see indexing progress.
   You'll get a notification when indexing starts and when it finishes.

SEARCHING
- Press Ctrl + Alt + Space (or click the tray icon) and start typing
- Enter: open the file   Ctrl + Enter: show in File Explorer   Esc: close
- PDFs show the page number; audio and video show the timestamp
- With VLC installed, audio/video opens at the matching moment
- Language: Settings -> Language (English / 繁體中文)

SPEED (this build runs on the CPU)
- Documents: about 0.1–0.3 s per chunk
- Photos: about 2–5 s each
- Video: about 30–60 s per minute of footage
- Big photo/video folders can take hours the first time. You can untick "Index video" in Settings,
  or exclude folders you don't need. After that, only new or changed files are processed.

WHERE DATA LIVES
Settings, index and log: C:\Users\<you>\.semsearch\
AI model: C:\Users\<you>\.cache\huggingface\
To uninstall, delete the app folder and the two folders above.

REPORTING PROBLEMS
Right-click the tray icon -> "Open log" and attach app.log to an issue:
https://github.com/a303990366/semsearch/issues
