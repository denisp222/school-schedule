"""Use registered Windows folders and Microsoft Word for school documents."""
import os
from pathlib import Path
import shutil
import subprocess


def documents_folder():
    if os.name=='nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                value=winreg.QueryValueEx(key,'Personal')[0]
            return Path(os.path.expandvars(value))
        except OSError:pass
    return Path.home()/'Documents'


def reports_folder():return documents_folder()/'Расписание'/'Отчёты'


def downloads_folder():
    if os.name=='nt':
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                value=winreg.QueryValueEx(key,'{374DE290-123F-4565-9164-39C4925E467B}')[0]
            return Path(os.path.expandvars(value))
        except OSError:pass
    return Path.home()/'Downloads'


def word_executable():
    if os.name=='nt':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINWORD.EXE') as key:
                    path=Path(winreg.QueryValueEx(key,'')[0].strip('"'))
                if path.is_file():return str(path)
            except OSError:pass
    return shutil.which('WINWORD.EXE')


def open_document(filename):
    path=Path(filename).resolve()
    if path.suffix.lower()=='.docx':
        # Match Explorer's normal Open action when Word is already registered.
        # Shell/DDE can reuse the user's running Word instead of forcing a new
        # /n instance that inherits the host process environment.
        if docx_uses_word():
            os.startfile(str(path),'open')
            return
        word=word_executable()
        if not word:raise FileNotFoundError('Microsoft Word не найден. Откройте файл из папки отчётов вручную.')
        subprocess.Popen([word,str(path)],close_fds=True)
    else:os.startfile(str(path))


def docx_uses_word():
    if os.name!='nt':return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.docx\UserChoice') as key:
            return str(winreg.QueryValueEx(key,'ProgId')[0]).lower().startswith('word.')
    except OSError:return False
