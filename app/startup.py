"""Local startup diagnostics. No school data, credentials or conversations."""
import json
import logging
import mimetypes
import os
import platform
from pathlib import Path
from threading import Lock
from time import monotonic

_started=monotonic()
_events=[]
_lock=Lock()


def record(message):
    stage=str(message.get('stage','unknown'))[:100]
    detail=str(message.get('message',''))[:500]
    # Error text must never turn this report into an accidental key export.
    import re
    detail=re.sub(r'sk-[A-Za-z0-9_-]+','[ключ скрыт]',detail)
    row={'stage':stage,'message':detail,'seconds':round(monotonic()-_started,2)}
    with _lock:
        _events.append(row);del _events[:-40]
    logging.info('UI startup: %s %s',stage,detail)


def report(resources,data,browser_version=None):
    from .distribution import voice_available
    from .version import VERSION
    with _lock:events=list(_events)
    total_ram=None
    if os.name=='nt':
        import ctypes
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(k,ctypes.c_ulonglong) for k in
                ('total','available','pageTotal','pageAvailable','virtualTotal','virtualAvailable','extended')]
        memory=Memory();memory.length=ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):total_ram=round(memory.total/1024**3,2)
    return {'appVersion':VERSION,'windows':platform.platform(),'architecture':platform.machine(),
            'cpuCount':os.cpu_count(),'ramGB':total_ram,'webviewVersion':browser_version,
            'voiceInstalled':voice_available(resources),'events':events,
            'systemMimeTypes':{suffix:mimetypes.guess_type('sample'+suffix)[0] for suffix in ('.js','.css','.svg')},
            'files':{name:(Path(resources)/'app/static'/name).is_file() for name in
                     ('startup.js','app.js','assistant.js','voice.js','extras.js','technology-ui.js')},
            'dataFolderWritable':os.access(data,os.W_OK)}
