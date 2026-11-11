"""Paths and small prerequisite checks for the distributable desktop app."""
import ctypes
import os
import sys
from pathlib import Path


def data_folder(folder):
    override=os.environ.get('SCHEDULE_DATA')
    if override:return Path(override).resolve()
    if (folder/'installed.json').is_file():
        return Path(os.environ['LOCALAPPDATA'])/'SchoolSchedule'/'Data'
    return folder/'data'


def webview_version():
    resources=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
    native=resources/'assets/webview'
    try:
        with os.add_dll_directory(str(native)):
            loader=ctypes.WinDLL(str(native/'WebView2Loader.dll'))
            call=loader.GetAvailableCoreWebView2BrowserVersionString
            call.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_void_p)]
            call.restype=ctypes.c_long
            value=ctypes.c_void_p()
            result=call(None,ctypes.byref(value))
            version=ctypes.wstring_at(value) if result==0 and value else None
            if value:
                ctypes.windll.ole32.CoTaskMemFree.argtypes=[ctypes.c_void_p]
                ctypes.windll.ole32.CoTaskMemFree(value)
            return version
    except OSError:return None


def webview_available():
    version=webview_version()
    try:return int(version.split('.')[0])>=109
    except (AttributeError,ValueError):return False


def voice_available(resources=None,folder=None):
    resources=Path(resources or getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
    folder=Path(folder or (Path(sys.executable).parent if getattr(sys,'frozen',False) else resources))
    settings=folder/'installed-components.json'
    if settings.is_file():
        import json
        try:
            if json.loads(settings.read_text(encoding='utf-8-sig')).get('voice') is not True:return False
        except (ValueError,OSError):return False
    speech=resources/'assets/speech-whisper'
    return (speech/'model.bin').is_file() and any((speech/name/'whisper-cli.exe').is_file() for name in ('bin','bin-blas'))
