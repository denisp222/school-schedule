"""Offline Russian Whisper transcription. Audio stays on this computer."""
import base64
import binascii
from array import array
from io import BytesIO
import logging
import math
import os
from pathlib import Path
import subprocess
import tempfile
import wave
from time import monotonic
from .speech_acceleration import available_engines

RATE=16000
MAX_SECONDS=90
RESOURCES=Path('assets/speech-whisper')


def decode_audio(pcm,rate):
    if rate!=RATE or type(rate) is not int:raise ValueError('Не удалось прочитать звук. Повторите запись.')
    maximum=RATE*2*MAX_SECONDS
    if not isinstance(pcm,str) or len(pcm)>maximum*4//3+8:
        raise ValueError('Запись слишком длинная. Продиктуйте просьбу частями.')
    try:audio=base64.b64decode(pcm,validate=True)
    except (ValueError,binascii.Error):raise ValueError('Не удалось прочитать запись. Повторите запись.') from None
    if len(audio)%2 or not 3200<=len(audio)<=maximum:
        raise ValueError('Запись слишком короткая или повреждена. Попробуйте ещё раз.')
    return audio


def recognize(pcm,rate=RATE):
    audio=decode_audio(pcm,rate)
    samples=array('h',audio)
    mean=sum(samples)/len(samples)
    rms=math.sqrt(sum((v-mean)**2 for v in samples)/len(samples))
    if rms<40:raise ValueError('Речь не слышна. Проверьте микрофон и попробуйте говорить чуть ближе к нему.')
    resources=RESOURCES.resolve()
    engines=available_engines(resources)
    if not engines or not (resources/'model.bin').is_file():
        raise ValueError('Не найдены файлы голосового ввода. Переустановите приложение свежим установщиком.')
    stream=BytesIO()
    with wave.open(stream,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE);wav.writeframes(audio)
    audio_context=min(1500,max(512,math.ceil((len(audio)/(RATE*2)+2)*50/64)*64))
    threads=str(min(6,max(1,(os.cpu_count() or 2)//2)))
    options=['-m','model.bin','-f','-','-l','ru','-nt','-np',
             '-of','transcript','-ac',str(audio_context),'-t',threads,'-bs','5','-nf','-sns']
    # A non-"-" output basename enables the segment callback on Windows.
    # No output format is selected, so no transcript file is created. The
    # native "-of -" instead opens CON and loses output in a windowless worker.
    # PCM arrives through stdin. Native code sees only ASCII relative model
    # paths and never needs a writable application folder or a Unicode WAV name.
    deadline=monotonic()+150
    env=dict(os.environ,OPENBLAS_NUM_THREADS=threads,OMP_NUM_THREADS=threads)
    if os.name=='nt':
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002|0x8000)
    result=None
    for executable,gpu in engines:
        if gpu:
            try:
                cache=Path(os.environ.get('SCHEDULE_DATA',tempfile.gettempdir()))/'speech-cache'
                cache.mkdir(parents=True,exist_ok=True)
                env.update(CUDA_CACHE_PATH=str(cache),CUDA_CACHE_MAXSIZE=str(256*1024*1024))
            except OSError:
                logging.info('GPU cache unavailable; using CPU recognition')
                continue
        remaining=deadline-monotonic()
        if remaining<=0:break
        command=[str(executable),*options,*([] if gpu else ['-ng'])]
        try:
            result=subprocess.run(command,cwd=resources,input=stream.getvalue(),capture_output=True,
                timeout=min(remaining,max(40,len(audio)/(RATE*2)*.75+5)) if gpu else remaining,
                env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        except (subprocess.TimeoutExpired,OSError):
            logging.warning('Voice engine %s unavailable; trying fallback',executable.parent.name)
            result=None;continue
        if result.returncode==0:
            logging.info('Voice engine used: %s',executable.parent.name)
            break
        logging.warning('Voice engine %s failed, code %s; trying fallback',executable.parent.name,result.returncode)
    if result is None or result.returncode:
        raise ValueError('Не удалось распознать запись. Попробуйте более короткое сообщение или введите его текстом.')
    text=' '.join(result.stdout.decode('utf-8',errors='replace').split()).strip()
    if not text:raise ValueError('Речь не распознана. Попробуйте говорить чуть ближе к микрофону.')
    if len(text)>4000:raise ValueError('Получилось слишком длинное сообщение. Продиктуйте просьбу частями.')
    return {'text':text}
