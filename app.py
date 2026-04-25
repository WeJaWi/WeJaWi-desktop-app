import sys
from PyQt5 import QtWidgets, QtCore
from ui.main_window import MainWindow
from core.logging_utils import get_logger

logger = get_logger(__name__)

def main():
    # HiDPI friendly
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("WeJaWi")

    logger.info("Starting WeJaWi UI")
    logger.debug("High DPI attributes enabled")

    win = MainWindow()
    win.show()

    try:
        exit_code = app.exec_()
        logger.info("Application event loop exited with code %s", exit_code)
        sys.exit(exit_code)
    except Exception:
        logger.exception("Unhandled exception in QApplication event loop")
        raise

if __name__ == "__main__":
    main()
