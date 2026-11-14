"""Windows UI adapter for the installed legacy reader, isolated in a temp copy."""
from pathlib import Path
import shutil,tempfile,time,os

def export(content,data,legacy_path=''):
    if os.name!='nt':raise ValueError('Импорт .chngf через Хронограф доступен в Windows.')
    from .chronograph_bridge import installation
    executable=installation(legacy_path);data=Path(data).resolve()
    if data.is_relative_to(executable.parent):raise ValueError('Выберите отдельную папку установленного Хронографа.')
    from pywinauto import Application,Desktop
    import win32gui,win32con
    with tempfile.TemporaryDirectory(prefix='chronograph-import-',dir=data,ignore_cleanup_errors=True) as tmp:
        stage=Path(tmp);legacy=stage/'legacy'
        shutil.copytree(executable.parent,legacy,ignore=shutil.ignore_patterns('Saves','help','*.chngf','*.hgf','unins*'))
        project=stage/'project.chngf';project.write_bytes(content)
        app=Application(backend='win32').start(str(legacy/'master.exe'),work_dir=str(legacy))
        desktop=Desktop(backend='win32')
        try:
            main=desktop.window(class_name='TMainForm',process=app.process);main.wait('visible',timeout=15)
            win32gui.PostMessage(main.handle,win32con.WM_COMMAND,3,0)
            load=desktop.window(class_name='TLoadSaveForm',process=app.process);load.wait('visible',timeout=12)
            load.child_window(title='Загрузить из файла...').click()
            opened=desktop.window(title='Открыть',class_name='#32770',process=app.process);opened.wait('visible',timeout=12)
            opened.child_window(class_name='Edit').set_edit_text(str(project));opened.child_window(title='&Открыть',class_name='Button').click();time.sleep(.5)
            outputs={}
            for command,name in ((15,'teacher-details.html'),(16,'room-details.html'),(17,'load-teachers.html'),(19,'week-teachers.html')):
                win32gui.PostMessage(main.handle,win32con.WM_COMMAND,command,0);time.sleep(.25)
                report_id=win32gui.GetMenuItemID(win32gui.GetSubMenu(win32gui.GetMenu(main.handle),4),0)
                win32gui.PostMessage(main.handle,win32con.WM_COMMAND,report_id,0);time.sleep(.25)
                deadline=time.monotonic()+5;options=None
                while options is None and time.monotonic()<deadline:
                    options=next((w for w in desktop.windows(process=app.process) if w.is_visible() and w.class_name() not in ('TMainForm','TApplication') and w.descendants(title='HTML')),None)
                    if options is None:time.sleep(.1)
                if options is None:raise ValueError('Хронограф не открыл штатный отчёт. Проверьте версию 3.0 Мастер.')
                for control in options.descendants(title='Выводить наименования предметов'):
                    if not control.get_check_state():control.click()
                html=options.descendants(title='HTML')
                if not html:raise ValueError('В установленной версии Хронографа нет HTML-экспорта.')
                html[0].click();options.descendants(title='ОК',class_name='TButton')[0].click()
                saved=desktop.window(title='Сохранение',class_name='#32770',process=app.process);saved.wait('visible',timeout=12)
                target=stage/name;saved.child_window(class_name='Edit').set_edit_text(str(target));saved.child_window(title='Со&хранить',class_name='Button').click()
                deadline=time.monotonic()+8
                while not target.exists() and time.monotonic()<deadline:time.sleep(.1)
                if not target.exists():raise ValueError('Хронограф не сохранил отчёт. Рабочее расписание не изменено.')
                time.sleep(.15);b=target.read_bytes()
                encoding='utf-8-sig' if b.startswith(b'\xef\xbb\xbf') or b'charset=utf-8' in b[:2000].lower() else 'cp1251'
                outputs[name]=b.decode(encoding)
            return outputs
        except ValueError:raise
        except Exception as error:
            raise ValueError('Не удалось прочитать проект штатным Хронографом. Проверьте файл в старой программе или загрузите его HTML-отчёты.') from error
        finally:
            if app.is_process_running():app.kill(soft=False)
            app.wait_for_process_exit(timeout=8)
