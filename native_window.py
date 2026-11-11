"""A small WinForms host for the official WebView2 control."""
import ctypes
import logging
import os
import threading
import json
import base64
from time import monotonic
from uuid import uuid4


def run_window(url, data, resources, on_ready, *, qa_browser_arguments='', qa_script='', qa_message=None):
    if (qa_browser_arguments or qa_script or qa_message) and not data.name.endswith('-qa'):
        raise ValueError('Window test hooks require a separate QA folder.')
    from concurrent.futures import ThreadPoolExecutor
    file_worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='schedule-files')
    file_worker.submit(lambda:None).result()
    from pythonnet import load
    runtime_args={'runtime_config':str(resources/'app.runtimeconfig.json')}
    if (resources/'dotnet/host/fxr').is_dir():runtime_args['dotnet_root']=str(resources/'dotnet')
    load('coreclr',**runtime_args)
    import clr
    from System import Environment
    logging.info('UI runtime version: %s',Environment.Version)
    for name in ('System.Windows.Forms','System.Drawing.Common','Microsoft.Win32.SystemEvents'):
        clr.AddReference(name)
    native=resources/'assets'/'webview'
    dll_directory=os.add_dll_directory(str(native))
    ctypes.WinDLL(str(native/'WebView2Loader.dll'))
    for name in ('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll'):
        clr.AddReference(str(native/name))
    from System import Action, Uri
    from System.Drawing import Icon, Size, Color
    from System.Threading import Thread, ThreadStart, ApartmentState, ExecutionContext
    from System.Windows.Forms import Application, Form, DockStyle, FormStartPosition, SaveFileDialog, DialogResult, HighDpiMode, Screen
    from Microsoft.Web.WebView2.WinForms import WebView2, CoreWebView2CreationProperties
    errors=[]

    def gui():
        try:
            Application.SetHighDpiMode(HighDpiMode.PerMonitorV2)
            Application.EnableVisualStyles()
            area=Screen.PrimaryScreen.WorkingArea
            form=Form();form.Text='Расписание'
            form.ClientSize=Size(min(1440,max(640,area.Width-32)),min(960,max(420,area.Height-64)))
            form.MinimumSize=Size(min(960,max(640,area.Width-32)),min(640,max(420,area.Height-64)))
            form.StartPosition=FormStartPosition.CenterScreen
            form.Icon=Icon(str(resources/'app/static/favicon.ico'))
            form.BackColor=Color.FromArgb(244,240,231)
            browser=WebView2();browser.Dock=DockStyle.Fill
            props=CoreWebView2CreationProperties();props.UserDataFolder=str(data/'window')
            if qa_browser_arguments:props.AdditionalBrowserArguments=qa_browser_arguments
            browser.CreationProperties=props
            form.Controls.Add(browser)
            save_threads=[]
            saved_files={}
            microphone_until=[0.0]

            def save_message(sender, args):
                if args.Source.split('#')[0].split('?')[0].rstrip('/') != url.rstrip('/'):
                    return
                try:
                    message=json.loads(args.WebMessageAsJson)
                    if message.get('kind')=='ui-startup':
                        from app.startup import record
                        record(message)
                        return
                    if message.get('kind')=='startup-diagnostics':
                        from app.startup import report
                        content=json.dumps(report(resources,data,str(browser.CoreWebView2.Environment.BrowserVersionString)),ensure_ascii=False,indent=2).encode('utf-8')
                        message.update(kind='save-export',name='Проверка запуска Расписания.json',content=base64.b64encode(content).decode('ascii'))
                    if message.get('kind')=='qa-result' and qa_message:
                        qa_message(message)
                        return
                    if message.get('kind')=='voice-permission':
                        microphone_until[0]=monotonic()+15
                        browser.CoreWebView2.PostWebMessageAsJson(json.dumps({'kind':'voice-permission-ready','id':message.get('id')}))
                        return
                    if message.get('kind') in ('open-export','open-export-folder'):
                        path=saved_files.get(message.get('token'))
                        def open_from_host():
                            try:
                                if path:
                                    if message['kind']=='open-export-folder':os.startfile(str(path.parent))
                                    else:
                                        from app.windows_files import open_document
                                        open_document(path)
                            except Exception:
                                logging.exception('Не удалось открыть готовый отчёт')
                                browser.CoreWebView2.PostWebMessageAsJson(json.dumps({'kind':'export-open-error','error':'Не удалось открыть файл. Отчёт сохранён. Нажмите «Открыть папку» и откройте документ из Microsoft Word.'},ensure_ascii=False))
                        form.BeginInvoke(Action(open_from_host))
                        return
                    if message.get('kind')!='save-export':return
                    name=os.path.basename(str(message['name']))
                    if os.path.splitext(name)[1].lower() not in ('.docx','.json','.csv'):
                        raise ValueError('Unexpected file format')
                    content=base64.b64decode(message['content'],validate=True)
                    if len(content)>30*1024*1024:raise ValueError('Export too large')
                except Exception:
                    logging.exception('Некорректный запрос сохранения')
                    return
                # Leave the WebView callback before opening a modal Windows UI.
                def choose_and_write():
                    logging.info('Export dialog opening')
                    from app.process_context import restricted_process,thread_restricted
                    logging.info('Export context: process_restricted=%s thread_restricted=%s',restricted_process(),thread_restricted())
                    dialog=SaveFileDialog()
                    reply={'kind':'save-export-result','id':message.get('id')}
                    try:
                        dialog.FileName=name
                        from app.windows_files import reports_folder,documents_folder
                        reports=reports_folder()
                        try:reports.mkdir(parents=True,exist_ok=True)
                        except OSError:reports=documents_folder()
                        if reports.is_dir():dialog.InitialDirectory=str(reports)
                        dialog.Title='Сохранить отчёт'
                        dialog.OverwritePrompt=True
                        dialog.AddExtension=True
                        dialog.DefaultExt=os.path.splitext(name)[1].lstrip('.')
                        dialog.Filter='Документ Word (*.docx)|*.docx' if name.endswith('.docx') else 'Файл экспорта|*.*'
                        # The actual atomic write below checks permissions. The
                        # common dialog's speculative write probe can reject
                        # virtual/OneDrive folders before any file is written.
                        if hasattr(dialog,'CheckWriteAccess'):dialog.CheckWriteAccess=False
                        result=dialog.ShowDialog()
                        logging.info('Export dialog closed: %s',result)
                        if result!=DialogResult.OK:
                            reply['cancelled']=True
                        else:
                            from app.file_save import save_with_fallback
                            logging.info('Export writing file')
                            path,fallback=file_worker.submit(save_with_fallback,dialog.FileName,content,data/'Готовые отчёты').result(timeout=15)
                            token=uuid4().hex;saved_files[token]=path
                            while len(saved_files)>50:del saved_files[next(iter(saved_files))]
                            reply['saved']=True
                            reply.update(fallback=fallback,token=token,name=path.name,folder=path.parent.name)
                    except PermissionError:
                        logging.exception('Нет доступа для сохранения экспорта')
                        reply['error']='Не удалось записать файл. Если он открыт в Word, закройте его. Затем сохраните под другим именем или выберите другую папку.'
                    except Exception:
                        logging.exception('Ошибка записи экспорта')
                        reply['error']='Не удалось сохранить файл. Проверьте, доступна ли выбранная папка и есть ли свободное место, затем повторите сохранение.'
                    finally:
                        dialog.Dispose()
                    logging.info('Export completed: saved=%s cancelled=%s',reply.get('saved'),reply.get('cancelled'))
                    form.BeginInvoke(Action(lambda:browser.CoreWebView2.PostWebMessageAsJson(json.dumps(reply,ensure_ascii=False))))
                # Shell/OneDrive dialogs have their own modal message loop.
                # Keep that loop off WebView's STA to avoid nested COM callbacks.
                thread=Thread(ThreadStart(choose_and_write))
                thread.SetApartmentState(ApartmentState.STA)
                save_threads[:]=[t for t in save_threads if t.IsAlive]
                save_threads.append(thread)
                # Use the host's own context, not a WebView callback's captured
                # impersonation context. The process token itself is unchanged.
                flow=ExecutionContext.SuppressFlow()
                try:thread.Start()
                finally:flow.Undo()

            def save_download(sender,args):
                dialog=SaveFileDialog()
                dialog.FileName=os.path.basename(args.ResultFilePath)
                dialog.Title='Сохранить файл расписания';dialog.OverwritePrompt=True
                args.Handled=True
                if dialog.ShowDialog(form)==DialogResult.OK:args.ResultFilePath=dialog.FileName
                else:args.Cancel=True
                dialog.Dispose()

            def initialized(sender,args):
                if not args.IsSuccess:
                    errors.append(RuntimeError('Не удалось открыть окно расписания: '+str(args.InitializationException)))
                    form.Close();return
                core=browser.CoreWebView2
                logging.info('WebView runtime version: %s',core.Environment.BrowserVersionString)
                logging.info('Window display: dpi=%s client=%sx%s',form.DeviceDpi,form.ClientSize.Width,form.ClientSize.Height)
                core.Settings.IsStatusBarEnabled=False
                core.Settings.AreDevToolsEnabled=False
                core.Settings.AreBrowserAcceleratorKeysEnabled=False
                core.DownloadStarting+=save_download
                core.WebMessageReceived+=save_message
                def navigation_finished(sender,event):
                    from app.startup import record
                    record({'stage':'navigation-completed' if event.IsSuccess else 'navigation-failed',
                            'message':'' if event.IsSuccess else str(event.WebErrorStatus)})
                core.NavigationCompleted+=navigation_finished
                def process_failed(sender,event):
                    from app.startup import record
                    record({'stage':'webview-process-failed','message':str(event.ProcessFailedKind)})
                core.ProcessFailed+=process_failed
                from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind,CoreWebView2PermissionState
                def permission_requested(sender,event):
                    if event.PermissionKind!=CoreWebView2PermissionKind.Microphone:return
                    same=str(event.Uri).split('#')[0].split('?')[0].rstrip('/')==url.rstrip('/')
                    event.State=(CoreWebView2PermissionState.Allow if same and monotonic()<microphone_until[0] else CoreWebView2PermissionState.Deny)
                    event.SavesInProfile=False;microphone_until[0]=0.0
                core.PermissionRequested+=permission_requested
                if qa_script:
                    def run_qa(sender,event):
                        if event.IsSuccess:core.ExecuteScriptAsync(qa_script)
                    core.NavigationCompleted+=run_qa

            browser.CoreWebView2InitializationCompleted+=initialized
            def closing(sender,event):
                if any(t.IsAlive for t in save_threads):event.Cancel=True
            form.FormClosing+=closing
            browser.Source=Uri(url)
            on_ready(lambda:form.BeginInvoke(Action(form.Close)))
            Application.Run(form)
            browser.Dispose();form.Dispose()
        except Exception as exc:
            logging.exception('Ошибка окна');errors.append(exc)

    ui=Thread(ThreadStart(gui));ui.SetApartmentState(ApartmentState.STA);ui.Start()
    while ui.IsAlive:ui.Join(100)
    file_worker.shutdown(wait=True,cancel_futures=True)
    dll_directory.close()
    if errors:raise errors[0]
