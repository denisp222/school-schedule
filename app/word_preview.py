"""Render a prepared report using the desktop copy of Microsoft Word."""
import logging
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from .windows_files import word_executable

_render_lock = Lock()


def _renderers(source: Path, target: Path):
    if word_executable():
        command = [sys.executable]
        if not getattr(sys, 'frozen', False):
            command.append(str(Path(__file__).resolve().parents[1] / 'launch.py'))
        yield 'Word', command + ['--word-preview', str(source), str(target)], 24
    for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
        root = os.environ.get(variable)
        if root:
            office = Path(root) / 'LibreOffice' / 'program' / 'soffice.com'
            if office.is_file():
                profile = (source.parent / 'profile').as_uri()
                yield 'LibreOffice', [str(office), '-env:UserInstallation=' + profile,
                                     '--headless', '--convert-to', 'pdf:writer_pdf_Export',
                                     '--outdir', str(target.parent), str(source)], 22
                break


def render_pdf(document: bytes, data: Path) -> tuple[bytes, str]:
    if sys.platform != 'win32':
        raise ValueError('Предпросмотр доступен в Windows. Отчёт можно сохранить.')
    if not _render_lock.acquire(timeout=5):
        raise ValueError('Word ещё готовит другой отчёт. Повторите просмотр чуть позже.')
    try:
        with TemporaryDirectory(prefix='word-preview-', dir=data, ignore_cleanup_errors=True) as folder:
            workspace = Path(folder).resolve()
            source, target = workspace / 'schedule.docx', workspace / 'schedule.pdf'
            commands = list(_renderers(source, target))
            if not commands:
                raise ValueError('Для предпросмотра нужен Microsoft Word или LibreOffice. Отчёт можно сохранить.')
            source.write_bytes(document)
            env = dict(os.environ, TEMP=str(workspace), TMP=str(workspace))
            for renderer, command, timeout in commands:
                try:
                    completed = subprocess.run(command, timeout=timeout, env=env,
                                               creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
                    if completed.returncode == 0 and target.is_file():
                        pdf = target.read_bytes()
                        if pdf.startswith(b'%PDF-'):
                            return pdf, renderer
                    logging.warning('%s report preview failed: exit=%s stderr=%r',
                                    renderer, completed.returncode, completed.stderr[-1200:])
                except subprocess.TimeoutExpired:
                    logging.warning('%s report preview timed out', renderer)
                except OSError:
                    logging.exception('Cannot launch %s for report preview', renderer)
                target.unlink(missing_ok=True)
            raise ValueError('Не удалось показать страницы документа. Отчёт можно сохранить и открыть в Word.')
    except OSError:
        logging.exception('Cannot create temporary Word preview')
        raise ValueError('Не удалось создать временный файл для просмотра. Отчёт можно сохранить.') from None
    finally:
        _render_lock.release()


def render_in_word(source: str, target: str) -> None:
    import pythoncom
    from win32com.client import DispatchEx

    pythoncom.CoInitialize()
    try:
        word = DispatchEx('Word.Application')
        try:
            word.Visible = False
            word.DisplayAlerts = 0
            previous_security = word.AutomationSecurity
            word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
            try:
                document = word.Documents.Open(source, ConfirmConversions=False, ReadOnly=True,
                                               AddToRecentFiles=False, Visible=False)
            finally:
                word.AutomationSecurity = previous_security
            try:
                document.ExportAsFixedFormat(target, 17, OpenAfterExport=False, IncludeDocProps=False)
            finally:
                document.Close(False)
        finally:
            word.Quit(False)
    finally:
        pythoncom.CoUninitialize()
