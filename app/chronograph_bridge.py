"""Use an installed Chronograph copy for its own file reader and HTML export.

No proprietary executable is distributed. Only a temporary copy is launched;
neither the installed legacy application nor the original project is modified.
"""
from pathlib import Path
import os,shutil,subprocess,tempfile,time

def installation(explicit=''):
    if explicit:
        path=Path(explicit.strip().strip('"')).expanduser().resolve()
        if path.name.casefold()!='master.exe' or not path.is_file():raise ValueError('Укажите master.exe из установленного Хронографа 3.0 Мастер.')
        return path
    roots=[Path.cwd().parent,Path.cwd(),Path('C:/')]
    import sys
    roots.extend((Path(sys.executable).parent,Path(sys.executable).parent.parent))
    for root in roots:
        for folder in root.glob('*'):
            if folder.is_dir() and ('хроно' in folder.name.casefold() or 'chrono' in folder.name.casefold()):
                p=folder/'master.exe'
                if p.is_file():return p.resolve()
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            for flag in (winreg.KEY_WOW64_32KEY,winreg.KEY_WOW64_64KEY):
                try:
                    with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',0,winreg.KEY_READ|flag) as key:
                        for n in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                with winreg.OpenKey(key,winreg.EnumKey(key,n)) as sub:
                                    name=winreg.QueryValueEx(sub,'DisplayName')[0]
                                    if 'хроно' not in name.casefold() and 'chrono' not in name.casefold():continue
                                    p=Path(winreg.QueryValueEx(sub,'InstallLocation')[0])/'master.exe'
                                    if p.is_file():return p.resolve()
                            except OSError:pass
                except OSError:pass
    except ImportError:pass
    raise ValueError('Для чтения .chngf нужен установленный Хронограф 3.0 Мастер. Укажите путь к его master.exe либо загрузите четыре штатных HTML-отчёта.')

def export_project(content,data,legacy_path=''):
    from .chronograph_windows import export
    return export(content,data,legacy_path)
