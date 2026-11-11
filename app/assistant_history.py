"""Durable conversations in the schedule database, outside its revision counter."""
import json
import re
from uuid import uuid4


class AssistantHistory:
    def __init__(self,store):
        self.store=store
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS assistant_threads (id TEXT PRIMARY KEY,date TEXT NOT NULL,title TEXT NOT NULL,updated TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS assistant_turns (id TEXT PRIMARY KEY,thread_id TEXT NOT NULL,created TEXT NOT NULL,request TEXT NOT NULL,response TEXT,error TEXT NOT NULL DEFAULT \'\',status TEXT NOT NULL DEFAULT \'pending\')')

    def start(self,thread_id,day,message):
        if not isinstance(message,str) or not message.strip() or len(message)>4000:raise ValueError('Напишите просьбу длиной до 4000 символов.')
        message=re.sub(r'sk-[A-Za-z0-9_-]{16,}','[ключ скрыт]',message)
        now=self.store.now();turn=uuid4().hex
        with self.store.connect() as db:
            if thread_id:
                row=db.execute('SELECT date FROM assistant_threads WHERE id=?',(thread_id,)).fetchone()
                if not row or row[0]!=day:raise ValueError('Диалог относится к другой дате или больше не найден. Начните новую просьбу.')
            else:
                thread_id=uuid4().hex
                db.execute('INSERT INTO assistant_threads VALUES (?,?,?,?)',(thread_id,day,' '.join(message.split())[:120],now))
            db.execute('INSERT INTO assistant_turns(id,thread_id,created,request) VALUES (?,?,?,?)',(turn,thread_id,now,message.strip()))
            db.execute('UPDATE assistant_threads SET updated=? WHERE id=?',(now,thread_id))
        return thread_id,turn

    def finish(self,turn,response=None,error='',status='understood'):
        # Only interpreted school conditions and human-readable text. No key,
        # HTTP headers, provider diagnostics, or full school prompt are saved.
        allowed=('date','reply','questions','unsupported','actions','labels','model')
        payload={k:response[k] for k in allowed if k in response} if response else None
        with self.store.connect() as db:
            db.execute('UPDATE assistant_turns SET response=COALESCE(?,response),error=?,status=? WHERE id=?',
                       (json.dumps(payload,ensure_ascii=False) if payload is not None else None,error,status,turn))
            db.execute('UPDATE assistant_threads SET updated=? WHERE id=(SELECT thread_id FROM assistant_turns WHERE id=?)',(self.store.now(),turn))

    def list(self,offset=0):
        if type(offset) is not int or offset<0:raise ValueError('Некорректная страница истории.')
        with self.store.connect() as db:
            rows=db.execute('SELECT id,date,title,updated FROM assistant_threads ORDER BY updated DESC LIMIT 100 OFFSET ?',(offset,)).fetchall()
        return [dict(zip(('id','date','title','updated'),r)) for r in rows]

    def get(self,thread_id):
        with self.store.connect() as db:
            thread=db.execute('SELECT id,date,title,updated FROM assistant_threads WHERE id=?',(thread_id,)).fetchone()
            if not thread:raise ValueError('Диалог не найден.')
            rows=db.execute('SELECT id,created,request,response,error,status FROM assistant_turns WHERE thread_id=? ORDER BY rowid',(thread_id,)).fetchall()
        return {**dict(zip(('id','date','title','updated'),thread)),
                'turns':[{'id':r[0],'created':r[1],'request':r[2],'response':json.loads(r[3]) if r[3] else None,'error':r[4],'status':r[5]} for r in rows]}

    def delete(self,thread_id):
        if not isinstance(thread_id,str) or not re.fullmatch('[a-f0-9]{32}',thread_id):
            raise ValueError('Диалог не найден.')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM assistant_threads WHERE id=?',(thread_id,)).fetchone():
                raise ValueError('Диалог уже удалён.')
            db.execute('DELETE FROM assistant_turns WHERE thread_id=?',(thread_id,))
            db.execute('DELETE FROM assistant_threads WHERE id=?',(thread_id,))

    def saved_at(self):
        with self.store.connect() as db:return db.execute('SELECT MAX(updated) FROM assistant_threads').fetchone()[0]

    def export(self):
        with self.store.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM assistant_threads ORDER BY updated')]
        return [self.get(i) for i in ids]

    @staticmethod
    def validate_import(rows):
        from datetime import date,datetime
        if not isinstance(rows,list) or len(rows)>10000:raise ValueError('Не удалось прочитать историю помощника в копии.')
        seen=set()
        for thread in rows:
            try:
                assert re.fullmatch('[a-f0-9]{32}',thread['id']) and thread['id'] not in seen
                seen.add(thread['id']);date.fromisoformat(thread['date']);datetime.fromisoformat(thread['updated'])
                assert isinstance(thread['title'],str) and len(thread['title'])<=120
                assert isinstance(thread['turns'],list) and len(thread['turns'])<=10000
                for turn in thread['turns']:
                    assert re.fullmatch('[a-f0-9]{32}',turn['id']) and isinstance(turn['request'],str) and len(turn['request'])<=4000
                    datetime.fromisoformat(turn['created'])
                    assert turn['status'] in ('pending','understood','applied','stale','error')
                    assert isinstance(turn['error'],str) and len(turn['error'])<=2000
                    if turn['response'] is not None:
                        assert isinstance(turn['response'],dict) and len(json.dumps(turn['response']))<=50000
            except (AssertionError,KeyError,ValueError,TypeError):
                raise ValueError('В копии повреждена история помощника. Расписание не изменено.') from None
        return rows

    @staticmethod
    def restore(db,rows):
        for thread in rows:
            db.execute('INSERT OR IGNORE INTO assistant_threads VALUES (?,?,?,?)',tuple(thread[k] for k in ('id','date','title','updated')))
            for turn in thread['turns']:
                db.execute('INSERT OR IGNORE INTO assistant_turns VALUES (?,?,?,?,?,?,?)',
                           (turn['id'],thread['id'],turn['created'],turn['request'],json.dumps(turn['response'],ensure_ascii=False) if turn['response'] else None,turn['error'],turn['status']))
