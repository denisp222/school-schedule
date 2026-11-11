"""Save a prepared export atomically; never damage an existing file on failure."""
import os
import logging
from pathlib import Path
from uuid import uuid4


def save_with_fallback(filename, content, folder):
    try:
        write_export(filename,content)
        return Path(filename),False
    except PermissionError:
        logging.exception('Chosen export path is not writable: %s',filename)
        from .windows_files import downloads_folder,reports_folder
        folders=[reports_folder(),downloads_folder()/'Школьное расписание',Path(folder)]
        original=Path(filename)
        for destination in folders:
            try:
                destination.mkdir(parents=True,exist_ok=True)
                target=destination/(original.stem+'-'+uuid4().hex[:8]+original.suffix)
                write_export(target,content)
                return target,True
            except PermissionError:
                logging.exception('Fallback export path is not writable: %s',destination)
                continue
        raise PermissionError('Не удалось сохранить отчёт ни в выбранную папку, ни в папку отчётов приложения.')


def write_export(filename, content):
    target = Path(filename)
    temporary = None
    try:
        # Python's tempfile can retry PermissionError indefinitely on Windows
        # directories. A unique exclusive filename fails immediately instead.
        temporary = target.parent / ('.schedule-' + uuid4().hex + '.tmp')
        try:stream=temporary.open('xb')
        except PermissionError:
            # A selected filename can be writable even when creating sibling
            # temporary files is forbidden. Never overwrite an existing report
            # through this non-atomic path.
            if target.exists():raise
            created=False
            try:
                with target.open('xb') as direct:
                    created=True;direct.write(content);direct.flush();os.fsync(direct.fileno())
                return
            except Exception:
                if created:target.unlink(missing_ok=True)
                raise
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
