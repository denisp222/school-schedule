"""Keep native solver failures outside the window and storage process."""
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def isolated():
    return os.environ.get('SCHEDULE_SOLVER_WORKER')!='1'


def calculate(kind, payload):
    with tempfile.TemporaryDirectory(prefix='schedule-calc-') as folder:
        source=Path(folder)/'input.json';target=Path(folder)/'output.json'
        source.write_text(json.dumps({'kind':kind,'payload':payload},ensure_ascii=False),encoding='utf-8')
        command=[sys.executable]
        if not getattr(sys,'frozen',False):command+=['-S',str(Path(__file__).resolve().parents[1]/'launch.py')]
        command+=['--solver-worker',str(source),str(target)]
        try:
            resources=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
            process=subprocess.run(command,timeout={'day':30,'annual':60,'speech':170}.get(kind,30),
                                   cwd=resources if kind=='speech' else None,
                                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),capture_output=True)
            if process.returncode or not target.exists():
                logging.error('Solver worker failed: code=%s stderr=%r',process.returncode,process.stderr[-2000:])
                if kind=='speech':raise ValueError('Голосовой ввод прервался. Повторите запись или введите просьбу текстом.')
                raise ValueError('Расчёт прервался. Ваше расписание сохранено. Попробуйте выполнить подбор ещё раз; если ошибка повторится, закройте и снова откройте приложение.')
            result=json.loads(target.read_text(encoding='utf-8'))
            if 'error' in result:
                logging.error('Solver worker error: %s',result['error'])
                if kind=='speech':raise ValueError('Не удалось включить голосовой ввод. Повторите запись или переустановите приложение свежим установщиком.')
                raise ValueError('Не удалось рассчитать расписание. Текущее расписание не изменено. Проверьте учебный план и ограничения.')
            return result['result']
        except subprocess.TimeoutExpired as exc:
            logging.error('Calculation timed out: kind=%s stderr=%r',kind,(exc.stderr or b'')[-2000:])
            if kind=='speech':raise ValueError('Распознавание заняло слишком много времени. Попробуйте более короткую запись.') from None
            raise ValueError('Расчёт не завершился вовремя. Текущее расписание сохранено. Попробуйте подобрать изменения только на один день.') from None


def worker(source,target):
    os.environ['SCHEDULE_SOLVER_WORKER']='1'
    import traceback
    try:
        request=json.loads(Path(source).read_text(encoding='utf-8'))
        if request['kind']=='annual':
            from .annual import build_week
            result=build_week(**request['payload'])
        elif request['kind']=='day':
            from .repair_constraints import solve_day
            result=solve_day(**request['payload'])
        elif request['kind']=='speech':
            from .speech import recognize
            try:result=recognize(**request['payload'])
            except ValueError as exc:result={'error':str(exc)}
        else:raise ValueError('Unknown calculation')
        response={'result':result}
    except Exception:response={'error':traceback.format_exc()}
    Path(target).write_text(json.dumps(response,ensure_ascii=False),encoding='utf-8')
