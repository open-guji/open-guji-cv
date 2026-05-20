"""Standalone entry point for PyInstaller-bundled guji-cv-ui executable.

When running as a frozen executable (PyInstaller), this module:
1. Adjusts paths so bundled resources (index.html) can be found
2. Launches the web server
3. Opens the browser
"""
import os
import sys


def main():
    # If running from PyInstaller bundle, adjust the HTML path
    if getattr(sys, 'frozen', False):
        # PyInstaller unpacks to sys._MEIPASS
        bundle_dir = sys._MEIPASS
        # Override the HTML_PATH in server module
        os.environ['GUJI_CV_WEB_DIR'] = os.path.join(bundle_dir, 'open_guji_cv', 'web')

    from open_guji_cv.web.server import start_server
    start_server(port=8632, open_browser=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        # In windowed mode (no console), show error in message box on Windows
        msg = f"启动失败: {e}"
        if sys.platform == "win32" and not sys.stderr:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, msg, "古籍 CV 工具台", 0x10)
        else:
            print(msg, file=sys.stderr or sys.stdout)
        sys.exit(1)
