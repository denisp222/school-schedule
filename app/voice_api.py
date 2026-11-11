"""Short-lived local speech processing, isolated from the desktop process."""
from threading import Lock
import logging
from time import monotonic
from fastapi import APIRouter
from .speech import decode_audio
from .solver_process import calculate

router=APIRouter(prefix='/api/assistant/voice')
_lock=Lock()


@router.post('')
def transcribe(body:dict):
    from .distribution import voice_available
    if not voice_available():raise ValueError('В этой установке голосовой ввод отключён. Просьбу можно ввести текстом.')
    pcm=body.get('pcm');rate=body.get('rate')
    decode_audio(pcm,rate)
    if not _lock.acquire(blocking=False):raise ValueError('Предыдущая запись ещё распознаётся. Дождитесь результата.')
    try:
        started=monotonic()
        result=calculate('speech',{'pcm':pcm,'rate':rate})
        if result.get('error'):raise ValueError(result['error'])
        logging.info('Voice recognition completed in %.2fs',monotonic()-started)
        return result
    finally:_lock.release()


@router.post('/format')
def format_dictation(body:dict):
    from .dictation import format_text,validate_text
    from .assistant_api import connection,context
    text=validate_text(body.get('text'))
    started=monotonic()
    try:
        result=format_text(connection(),text,context().store.read()['state'])
        logging.info('Dictation formatting completed in %.2fs',monotonic()-started)
        return result
    except ValueError as error:
        logging.info('Dictation formatting unavailable after %.2fs: %s',monotonic()-started,str(error)[:250])
        return {'text':text,'formatted':False,'warning':'Текст распознан. Автоматически оформить его не удалось, проверьте сообщение перед отправкой.'}
