"""Background checks and explicitly approved updates inside the main window."""
from copy import deepcopy
import json,logging,os,threading
from pathlib import Path
import httpx
from fastapi import APIRouter
from . import updates
from .version import VERSION

router=APIRouter(prefix='/api/updates')


class UpdateManager:
    def __init__(self,data,resources,folder,close,*,transport=None):
        self.data=Path(data);self.resources=Path(resources);self.folder=Path(folder)
        self.close=close;self.transport=transport;self.lock=threading.RLock();self.cancelled=threading.Event()
        self.payload=None;self.installer=None
        self.view={'stage':'idle','currentVersion':VERSION,'version':None,'done':0,'total':0,'message':''}
        self.attempt=self.data/'update-attempt.json'
        try:
            old=json.loads(self.attempt.read_text(encoding='utf-8'))
            if updates.version(VERSION)>=updates.version(old['version']):self.attempt.unlink(missing_ok=True)
            else:self.view['message']='Предыдущее обновление не завершилось. Программа открыта в прежней версии; обновление можно повторить вручную.'
        except (OSError,ValueError,KeyError):pass

    def status(self):
        with self.lock:return deepcopy(self.view)

    def check(self,automatic=False):
        with self.lock:
            if self.view['stage'] not in ('idle','error','current','available'):return self.status()
            if automatic and ((self.data/'updates-disabled').exists() or not (self.folder/'installed.json').exists() or self.attempt.exists()):return self.status()
            self.view.update(stage='checking',message='Проверяем обновления…')
        def work():
            try:
                config=updates.channel()
                with httpx.Client(timeout=httpx.Timeout(5,connect=3),transport=self.transport,follow_redirects=False) as client:
                    payload=updates.fetch_manifest(client,config) if config else None
                with self.lock:
                    self.payload=payload
                    self.view.update(stage='available' if payload else 'current',version=payload['version'] if payload else None,
                        total=payload['asset']['size'] if payload else 0,message='Доступна новая версия.' if payload else 'Установлена последняя версия.')
            except Exception:
                logging.info('Background update check unavailable',exc_info=True)
                with self.lock:self.view.update(stage='error',message='Не удалось проверить обновления. Можно продолжать работу и попробовать позже.')
        threading.Thread(target=work,daemon=True).start()
        return self.status()

    def download(self):
        with self.lock:
            if self.view['stage']!='available' or not self.payload:raise ValueError('Сначала проверьте наличие обновления.')
            self.cancelled.clear();self.view.update(stage='downloading',done=0,message='Подключаемся для загрузки…')
            payload=deepcopy(self.payload)
        def progress(done,total):
            if self.cancelled.is_set():raise InterruptedError()
            with self.lock:self.view.update(done=done,total=total,message='Загружаем обновление…')
        def work():
            try:
                with httpx.Client(timeout=httpx.Timeout(30,connect=8),transport=self.transport,follow_redirects=False) as client:
                    path=updates.download(client,payload,self.data/'updates',progress)
                with self.lock:
                    if self.cancelled.is_set():self.view.update(stage='available',message='Загрузка отложена.');return
                    self.installer=path;self.view.update(stage='ready',done=payload['asset']['size'],message='Обновление загружено. Можно установить и перезапустить программу.')
            except Exception:
                logging.info('Update download interrupted',exc_info=True)
                with self.lock:self.view.update(stage='available' if self.cancelled.is_set() else 'error',message='Загрузка отложена.' if self.cancelled.is_set() else 'Не удалось загрузить обновление. Программа продолжает работать, расписание сохранено.')
        threading.Thread(target=work,daemon=True).start()
        return self.status()

    def install(self):
        with self.lock:
            if self.view['stage']!='ready' or not self.installer:raise ValueError('Сначала загрузите обновление.')
            updates.backup_before_update(self.data)
            temporary=self.attempt.with_suffix('.tmp')
            temporary.write_text(json.dumps({'version':self.payload['version'],'fromVersion':VERSION}),encoding='utf-8')
            os.replace(temporary,self.attempt)
            # Only close the timetable after the independent installer helper
            # starts successfully. Failed attempts never run again on startup.
            updates.launch_installer(self.installer,self.folder,self.payload)
            self.view.update(stage='installing',message='Устанавливаем обновление. Приложение откроется снова.')
            threading.Timer(.8,self.close).start()
        return self.status()


def manager():
    from .server import app
    value=getattr(app.state,'update_manager',None)
    if value is None:raise ValueError('Обновление доступно в обычном окне приложения.')
    return value


@router.get('/status')
def status():return manager().status()

@router.post('/check')
def check(body:dict):return manager().check(body.get('automatic') is True)

@router.post('/download')
def download(body:dict):
    if body.get('confirmed') is not True:raise ValueError('Подтвердите загрузку обновления.')
    return manager().download()

@router.post('/install')
def install(body:dict):
    if body.get('confirmed') is not True:raise ValueError('Подтвердите установку и перезапуск.')
    return manager().install()

@router.post('/cancel')
def cancel(body:dict):
    manager().cancelled.set()
    return manager().status()
