import sys
import threading
import traceback
from PySide6.QtWidgets import QApplication, QMessageBox
from brain import ChatBrain
from gui import ChatWindow

def exception_hook(exc_type, exc_value, exc_traceback):
    """Global handler for uncaught exceptions."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    print("An unexpected error occurred:\n")
    traceback.print_exception(exc_type, exc_value, exc_traceback)

    try:
        app = QApplication.instance()
        if app:
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Critical)
            msg.setWindowTitle("Error")
            msg.setText("An unexpected error occurred. Check console for details.")
            msg.exec()
    except Exception:
        pass

    print("\nPress Enter to exit...")
    input()
    sys.exit(1)

# Set global exception hook
sys.excepthook = exception_hook

# Patch threading to catch exceptions in all threads
_original_thread_init = threading.Thread.__init__

def thread_init(self, *args, **kwargs):
    _original_thread_init(self, *args, **kwargs)
    _run = self.run
    def run_with_hook(*a, **k):
        try:
            _run(*a, **k)
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            exception_hook(exc_type, exc_value, exc_traceback)
    self.run = run_with_hook

threading.Thread.__init__ = thread_init

def main():
    try:
        app = QApplication(sys.argv)

        brain = ChatBrain()
        window = ChatWindow(brain)
        window.show()

        sys.exit(app.exec())
    except Exception:
        exc_type, exc_value, exc_traceback = sys.exc_info()
        exception_hook(exc_type, exc_value, exc_traceback)

if __name__ == "__main__":
    main()
