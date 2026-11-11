"""Native Windows window. The server lifetime follows this window, not Edge."""
from __future__ import annotations
import ctypes, hashlib, json, logging, os, socket, sys, threading, time
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

def health(port):
    try:
        with build_opener(ProxyHandler({})).open(f'http://127.0.0.1:{port}/api/health',timeout=.5) as r:return json.load(r)
    except Exception:return None

def choose_port(data):
    from app.process_context import restricted_process
    restricted=restricted_process()
    available=None
    for port in range(8765,8796):
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1',port))
                if available is None:available=port
                continue
            except OSError:pass
        info=health(port)
        if info and info.get('app')=='raspisanie' and Path(info.get('data','')).resolve()==data.resolve():
            # A visible current window is handled by the mutex above. Do not
            # attach a fresh WebView to an orphan or outdated server process.
            from urllib.request import Request
            logging.info('Stopping detached desktop server: port=%s version=%s',port,info.get('version'))
            try:
                request=Request(f'http://127.0.0.1:{port}/api/shutdown',data=b'{}',headers={'Content-Type':'application/json'})
                build_opener(ProxyHandler({})).open(request,timeout=2).close()
            except Exception:logging.exception('Detached server did not stop promptly')
    if available is None:raise RuntimeError('Все рабочие подключения заняты.')
    return available,False

def focus_existing(data):
    from ctypes import wintypes
    try:
        row=json.loads((data/'server.json').read_text(encoding='utf-8'))
        pid=row['pid']
        from urllib.parse import urlparse
        info=health(urlparse(row['url']).port)
        if not info or info.get('pid')!=pid or info.get('app')!='raspisanie' or Path(info.get('data','')).resolve()!=data.resolve():return False
    except Exception:return False
    user=ctypes.windll.user32;found=[]
    @ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def visit(hwnd,_):
        owner=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid and user.IsWindowVisible(hwnd):
            user.ShowWindow(hwnd,9);user.SetForegroundWindow(hwnd);found.append(hwnd)
        return True
    user.EnumWindows(visit,0)
    return bool(found)

def main():
    os.environ['SCHEDULE_DESKTOP']='1'
    resources=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    folder=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    from app.distribution import data_folder
    data=data_folder(folder).resolve()
    data.mkdir(parents=True,exist_ok=True);os.environ['SCHEDULE_DATA']=str(data)
    logging.basicConfig(filename=data/'application.log',level=logging.INFO,encoding='utf-8',format='%(asctime)s %(levelname)s %(message)s')
    from app.process_context import restricted_process
    from app.version import VERSION
    restricted=restricted_process()
    logging.info('Desktop context: restricted=%s',restricted)
    if restricted and sys.platform=='win32' and not data.name.endswith('-qa') and '--no-browser' not in sys.argv:
        ctypes.windll.user32.MessageBoxW(0,'Этот способ запуска ограничивает сохранение документов.\n\nЗакройте окно и запустите «Расписание» обновлённым ярлыком на рабочем столе.','Запустите приложение с рабочего стола',0x40)
        return
    no_window='--no-browser' in sys.argv;mutex=None
    if sys.platform=='win32' and not no_window:
        kernel=ctypes.windll.kernel32;kernel.CreateMutexW.restype=ctypes.c_void_p
        mutex=kernel.CreateMutexW(None,False,'Local\\Raspisanie-'+hashlib.sha256(str(data).casefold().encode()).hexdigest()[:20])
        if kernel.GetLastError()==183:
            focused=False
            for _ in range(100):
                if focus_existing(data):focused=True;break
                time.sleep(.1)
            kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            kernel.CloseHandle(mutex)
            return
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('School.Raspisanie.2026')
    if sys.platform=='win32' and not no_window and (folder/'installed.json').is_file():
        try:
            from app.updates import startup_update
            if startup_update(data,resources,folder):
                if mutex:
                    ctypes.windll.kernel32.CloseHandle.argtypes=[ctypes.c_void_p]
                    ctypes.windll.kernel32.CloseHandle(mutex)
                return
        except Exception:
            logging.exception('Update postponed; opening current version')
    port,running=choose_port(data);url=f'http://127.0.0.1:{port}'
    server=None;thread=None
    if not running:
        import uvicorn
        from app.server import app
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_config=None,access_log=False,timeout_graceful_shutdown=2))
        app.state.shutdown=lambda:setattr(server,'should_exit',True)
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        deadline=time.monotonic()+15
        while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
        if not server.started:raise RuntimeError('Не удалось запустить расписание. Подробности сохранены в журнале приложения.')
    if no_window:
        if thread:thread.join()
        return
    (data/'server.json').write_text(json.dumps({'pid':os.getpid(),'url':url,'version':VERSION}),encoding='utf-8')
    from native_window import run_window
    def on_ready(close):
        if server:
            from app.server import app
            def shutdown():
                server.should_exit=True
                close()
            app.state.shutdown=shutdown
    try:run_window(url,data,resources,on_ready)
    finally:
        if server:server.should_exit=True
        if thread:thread.join(timeout=6)
        try:
            marker=data/'server.json'
            if json.loads(marker.read_text(encoding='utf-8')).get('pid')==os.getpid():marker.unlink()
        except (OSError,ValueError):pass
        if mutex:
            ctypes.windll.kernel32.CloseHandle.argtypes=[ctypes.c_void_p]
            ctypes.windll.kernel32.CloseHandle(mutex)

def run():
    try:main()
    except Exception as exc:
        logging.exception('Ошибка запуска')
        if sys.platform=='win32':ctypes.windll.user32.MessageBoxW(0,'Не удалось открыть расписание. Данные не удалены.\n\nЗакройте другие окна программы и повторите запуск. Подробности ошибки сохранены для проверки.','Расписание',0x10)
        else:raise

if __name__=='__main__':run()
