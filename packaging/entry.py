"""PyInstaller 進入點。"""
import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from semsearch.app import main
    main()
