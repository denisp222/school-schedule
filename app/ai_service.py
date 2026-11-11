"""DeepSeek/OpenRouter interpreter. Portable credentials require encryption."""
from __future__ import annotations

import base64
import ctypes
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from time import sleep

import httpx
from . import ai_budget
from .version import VERSION


class AssistantError(ValueError):
    no_charge=False


def provider_error(response, key):
    """Classify an upstream refusal without exposing credentials or raw HTML."""
    try:
        error = response.json().get('error', {})
        message = error.get('message', '') if isinstance(error, dict) else error if isinstance(error, str) else ''
    except (ValueError, AttributeError):
        message = re.sub(r'<[^>]*>', ' ', response.text[:16_000])
    message = str(message).replace(key, '[secret]') if key else str(message)
    message = re.sub(r'sk-[A-Za-z0-9_-]+|Bearer\s+\S+', '[secret]', message, flags=re.I)
    message = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]+|\b(?:\d{1,3}\.){3}\d{1,3}\b', '[private]', message)
    message = re.sub(r'[A-Za-z0-9_=-]{32,}', '[private]', message)
    message = ' '.join(message.split())[:500]
    lower = message.lower()
    category = 'unknown'
    if any(s in lower for s in ('country', 'region', 'location', 'geographic')):
        category = 'region'
    elif any(s in lower for s in ('cloudflare', 'security policy', 'access denied', 'just a moment', 'blocked', 'captcha')) and 'account' not in lower:
        category = 'network_policy'
    elif any(s in lower for s in ('account', 'permission', 'guardrail', 'scope', 'workspace')):
        category = 'account_policy'
    return category, message


def protect_secret(value: str, *, decrypt=False) -> str:
    """Windows DPAPI, bound to the signed-in user. No plaintext fallback."""
    if os.name != 'nt':
        raise AssistantError('Сохранение ключа поддерживается в приложении для Windows.')
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    raw = base64.b64decode(value, validate=True) if decrypt else value.encode('utf-8')
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = Blob(len(raw), buffer)
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise AssistantError('Windows не смогла прочитать или сохранить ключ. Введите его заново в настройках помощника.')
    try:
        result = ctypes.string_at(target.data, target.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        kernel.LocalFree(target.data)


def free_model(value):
    if not isinstance(value, str) or not (
        value == 'openrouter/free' or re.fullmatch(r'[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.:-]+:free', value)
    ):
        raise AssistantError('Выберите бесплатную модель: openrouter/free или идентификатор с окончанием :free.')
    return value


def allowed_model(value,paid=False):
    if paid and value==ai_budget.PAID_MODEL:return value
    return free_model(value)


def provider_of(data):
    provider=data.get('provider','openrouter')
    if provider not in ('deepseek','openrouter'):
        raise AssistantError('Выберите DeepSeek API или OpenRouter в настройках помощника.')
    return provider


def provider_name(provider):return 'DeepSeek' if provider=='deepseek' else 'OpenRouter'


def key_field(provider):return 'deepseekKey' if provider=='deepseek' else 'key'


def selected_model(data,provider):
    return ai_budget.DIRECT_MODEL if provider=='deepseek' else allowed_model(data.get('model','openrouter/free'),data.get('paidEnabled',False))


class OpenRouter:
    def __init__(self, path: Path, *, transport=None):
        self.path = path
        self.transport = transport
        self.lock = threading.Lock()
        self.request_lock = threading.Lock()

    def _read(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            raise AssistantError('Не удалось прочитать настройки помощника. Сохраните подключение заново.') from None

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        try:
            with temp.open('w', encoding='utf-8') as handle:
                json.dump(data, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except OSError:
            raise AssistantError('Не удалось сохранить настройки помощника. Закройте второе окно приложения и повторите.') from None

    def status(self):
        with self.lock:
            data = self._read()
            provider=provider_of(data)
            paid=provider=='deepseek' or bool(data.get('paidEnabled',False))
            usage = data.get('usage', {})
            if usage.get('date') != datetime.now(timezone.utc).date().isoformat():
                usage = {}
            return {'provider':provider,'providerName':provider_name(provider),
                    'configured':bool(data.get(key_field(provider))),
                    'connections':{'deepseek':bool(data.get('deepseekKey')),'openrouter':bool(data.get('key'))},
                    'openrouterModel':data.get('model','openrouter/free'),
                    'model':selected_model(data,provider),
                    'networkMode': data.get('networkMode', 'system'),
                    'requestsToday': usage.get('requests', 0), 'tokensToday': usage.get('tokens', 0),
                    'freeOnly':not paid,'paidEnabled':paid,
                    'budget':ai_budget.summary(data)}

    def configure(self, body):
        if not self.request_lock.acquire(blocking=False):
            raise AssistantError('Дождитесь ответа помощника, затем меняйте подключение.')
        try:return self._configure(body)
        finally:self.request_lock.release()

    def _configure(self, body):
        key = body.get('apiKey', '')
        if not isinstance(key, str) or len(key) > 512:
            raise AssistantError('Проверьте ключ помощника.')
        key = key.strip()
        with self.lock:
            data = self._read()
            provider=provider_of({'provider':body.get('provider',provider_of(data))})
            if key:
                if provider=='deepseek':
                    if key.startswith('sk-or-') or not re.fullmatch(r'sk-[A-Za-z0-9_-]{16,}',key):
                        raise AssistantError('Нужен отдельный ключ DeepSeek API, начинающийся с sk-. Создайте его в личном кабинете DeepSeek.')
                elif not re.fullmatch(r'sk-or-[A-Za-z0-9_-]{16,}',key):
                    raise AssistantError('Ключ OpenRouter должен начинаться с sk-or-. Скопируйте его целиком со страницы ключей.')
            if provider=='deepseek':
                model=body.get('model',ai_budget.DIRECT_MODEL)
                if model!=ai_budget.DIRECT_MODEL:
                    raise AssistantError('Для прямого подключения выберите DeepSeek Flash.')
            else:
                paid=body.get('paidEnabled',data.get('paidEnabled',False)) is True
                model=allowed_model(body.get('model',data.get('model','openrouter/free')),paid)
                paid=paid and model==ai_budget.PAID_MODEL
            limit=ai_budget.usd(body.get('monthlyLimitUSD',data.get('monthlyLimitUSD','1')))
            if limit<ai_budget.usd('0.01') or limit>100:raise AssistantError('Укажите месячный предел расходов от $0,01 до $100.')
            network = body.get('networkMode', data.get('networkMode', 'system'))
            if network not in ('system', 'direct'):
                raise AssistantError('Выберите системное подключение или прямое подключение без прокси.')
            if body.get('removeKey') is True:
                data.pop(key_field(provider), None)
            elif key:
                data[key_field(provider)] = protect_secret(key)
            data['provider']=provider
            if provider=='openrouter':
                data['model']=model
                data['paidEnabled']=paid
            data['networkMode'] = network
            data['monthlyLimitUSD']=str(limit)
            self._write(data)
        return self.status()

    def _request(self, method, route, *, payload=None, key,provider='openrouter',timeout=None):
        name=provider_name(provider)
        base='https://api.deepseek.com/' if provider=='deepseek' else 'https://openrouter.ai/api/v1/'
        with self.lock:
            network = self._read().get('networkMode', 'system')
        try:
            limit=httpx.Timeout(45,connect=10) if timeout is None else httpx.Timeout(max(.1,timeout),connect=min(3,max(.1,timeout)))
            with httpx.Client(transport=self.transport, timeout=limit,
                              follow_redirects=False, trust_env=network != 'direct') as client:
                headers={'Authorization':'Bearer '+key,'User-Agent':'SchoolSchedule/'+VERSION}
                if provider=='openrouter':headers['X-OpenRouter-Title']='School Schedule'
                response=client.request(method,base+route,headers=headers,json=payload)
        except (httpx.ConnectError,httpx.ConnectTimeout,httpx.PoolTimeout):
            error=AssistantError(f'Не удалось подключиться к {name}. Проверьте интернет и повторите просьбу.')
            error.no_charge=True;error.retryable=True
            raise error from None
        except httpx.TimeoutException:
            raise AssistantError('Помощник не ответил вовремя. Попробуйте позже; расписание не изменено.') from None
        except httpx.RequestError:
            raise AssistantError(f'Не удалось связаться с {name}. Проверьте интернет и доступность сервиса. Расписание не изменено.') from None
        category, detail = provider_error(response, key) if not response.is_success else ('', '')
        if not response.is_success:
            logging.warning('%s refusal: endpoint=%s status=%s category=%s reason=%s',
                            name,route,response.status_code,category,detail)
        messages = {
            401: 'OpenRouter не принял ключ. Скопируйте действующий ключ в настройки помощника.',
            402: 'Недостаточно средств на счёте OpenRouter. Пополните баланс в личном кабинете.',
            403: 'OpenRouter запретил этот запрос. Проверьте доступность сервиса и разрешения ключа.',
            404: 'Эта модель сейчас недоступна. Выберите другую модель в настройках помощника.',
            429: 'Достигнут лимит OpenRouter или бесплатная модель занята. Попробуйте позже. Расписание не изменено.',
        }
        if provider=='deepseek':
            messages.update({401:'DeepSeek не принял ключ. Создайте ключ в личном кабинете DeepSeek API и сохраните его в настройках.',
                402:'Недостаточно средств на счёте DeepSeek API. Пополните баланс в личном кабинете DeepSeek.',
                403:'DeepSeek ограничил доступ. Проверьте доступность сервиса и разрешения ключа.',
                429:'DeepSeek сейчас занят или ограничил частоту запросов. Повторите позже; расписание не изменено.'})
        if response.status_code == 403:
            if category == 'region':
                exc=AssistantError(f'{name} ограничил доступ для текущего сетевого подключения или региона. Попробуйте другое подключение.')
                exc.no_charge=True;raise exc
            if category == 'network_policy':
                exc=AssistantError(f'Защита {name} отклонила подключение. Попробуйте позже или используйте другое сетевое подключение. Причина сохранена для проверки.')
                exc.no_charge=True;raise exc
            if category == 'account_policy':
                exc=AssistantError(f'{name} ограничил запрос настройками аккаунта или ключа. Проверьте разрешения в личном кабинете.')
                exc.no_charge=True;raise exc
        if response.status_code in (400, 422):
            exc=AssistantError('Модель не приняла формат запроса. Причина сохранена для проверки; расписание не изменено.')
            exc.no_charge=True;raise exc
        if response.status_code in messages:
            exc=AssistantError(messages[response.status_code]);exc.no_charge=True
            exc.retryable=response.status_code==429
            raise exc
        if not response.is_success:
            error=AssistantError('Модель сейчас не смогла обработать запрос. Повторите позже или выберите другую модель.')
            # Only an explicit upstream rejection is safe to repeat. Unknown
            # transport failures retain their reserve and are not retried.
            error.retryable=response.status_code in (502,503,504)
            raise error
        if len(response.content) > 256_000:
            raise AssistantError('Помощник прислал слишком большой ответ. Сократите просьбу и повторите.')
        try:
            result = response.json()
            if not isinstance(result, dict) or 'error' in result:
                raise ValueError()
            return result
        except ValueError:
            raise AssistantError(f'{name} прислал неполный ответ. Повторите запрос; расписание не изменено.') from None

    def _credentials(self):
        with self.lock:
            data = self._read()
        provider=provider_of(data)
        field=key_field(provider)
        if not data.get(field):
            raise AssistantError(f'Сначала добавьте ключ {provider_name(provider)} в настройках помощника.')
        return protect_secret(data[field],decrypt=True),selected_model(data,provider),provider

    def account_links(self,provider=None):
        with self.lock:provider=provider_of({'provider':provider}) if provider is not None else provider_of(self._read())
        return ({'keys':'https://platform.deepseek.com/api_keys','balance':'https://platform.deepseek.com/top_up'}
                if provider=='deepseek' else
                {'keys':'https://openrouter.ai/settings/keys','balance':'https://openrouter.ai/settings/credits'})

    def _deepseek_balance(self,key,*,timeout=None):
        result=self._request('GET','user/balance',key=key,provider='deepseek',timeout=timeout)
        rows=result.get('balance_infos')
        if type(result.get('is_available')) is not bool or not isinstance(rows,list):
            raise AssistantError('DeepSeek не вернул данные баланса. Платный запрос не отправлен.')
        balances=[]
        for row in rows:
            if not isinstance(row,dict) or row.get('currency') not in ('USD','CNY'):continue
            if 'total_balance' not in row or any(r['currency']==row['currency'] for r in balances):
                raise AssistantError('Не удалось прочитать баланс DeepSeek. Платный запрос не отправлен.')
            balances.append({'currency':row['currency'],'amount':str(ai_budget.usd(row['total_balance']))})
        if not balances:raise AssistantError('DeepSeek не вернул баланс в поддерживаемой валюте. Платный запрос не отправлен.')
        return {'available':result['is_available'],'balances':balances,'provider':'deepseek'}

    def balance(self):
        key,_,provider=self._credentials()
        if provider=='deepseek':return self._deepseek_balance(key)
        data=self._request('GET','credits',key=key).get('data',{})
        if 'total_credits' not in data or 'total_usage' not in data:
            raise AssistantError('OpenRouter не вернул данные баланса. Проверьте подключение.')
        credits=ai_budget.usd(data['total_credits'])-ai_budget.usd(data['total_usage'])
        return {'balanceUSD':str(credits)}

    def check(self):
        key,_,provider=self._credentials()
        if provider=='deepseek':
            result=self._deepseek_balance(key)
            return {**result,'connected':True,'keyAccepted':True,'modelTested':False}
        result = self._request('GET', 'key', key=key).get('data', {})
        quota = result.get('free_model_daily_requests', {})
        return {'connected': True, 'keyAccepted': True, 'modelTested': False,
                'remaining': quota.get('remaining'), 'limit': quota.get('limit')}

    def probe(self):
        """One model call using an entirely fictional school, never Store."""
        from .ai_planner import messages_for
        state = {'teachers': [{'id': 'demo-t', 'name': 'Тестовый преподаватель Альфа'},
                              {'id': 'demo-other', 'name': 'Тестовый преподаватель Гамма'}],
                 'classes': [{'id': 'demo-c', 'name': 'Тестовый класс Бета'}],
                 'subjects': [{'id':'demo-s','name':'Тестовый предмет'}],
                 'rooms': [{'id':'demo-r','name':'Тестовый кабинет'}], 'plan': [], 'baseLessons': [], 'days': {}}
        state['baseLessons']=[{'id':f'demo-l{p}','day':0,'period':p,'classIds':['demo-c'],
                               'subjectId':'demo-s','teacherIds':['demo-t' if p==2 else 'demo-other'],
                               'roomIds':['demo-r'],'locked':False} for p in (1,2,3)]
        prompt = ('Тестовый преподаватель Альфа отсутствует только на втором уроке. '
                  'Тестовый класс Бета должен начать занятия вторым уроком и закончить не позже шестого.')
        result, model = self.interpret(messages_for(state, '2026-11-09', prompt, []))
        expected = [{'type': 'teacher_absence', 'teacherId': 'demo-t', 'first': 2, 'last': 2},
                    {'type': 'class_day', 'classId': 'demo-c', 'first': 2, 'last': 6}]
        actual = result.get('actions', [])
        ready = (result.get('date') == '2026-11-09' and not result.get('questions') and not result.get('unsupported')
                 and isinstance(actual, list) and len(actual) == 2 and all(row in actual for row in expected))
        return {'connected': True, 'modelReady': ready, 'model': model,
                'message': ('Модель ответила и верно поняла оба тестовых условия. Школьные данные не отправлялись.' if ready
                            else 'Модель ответила, но неточно поняла тестовые условия. Выберите другую модель перед работой с расписанием.')}

    def interpret(self,messages,**options):
        deadline=options.get('deadline_seconds')
        end=monotonic()+deadline if deadline is not None else None
        for attempt in range(2):
            if end is not None:options['deadline_seconds']=max(.1,end-monotonic())
            try:return self._interpret_once(messages,**options)
            except AssistantError as error:
                if attempt or not getattr(error,'retryable',False) or end is not None and end-monotonic()<2:raise
                sleep(.35)

    def _interpret_once(self,messages,*,expected_provider=None,expected_model=None,response_schema=None,deadline_seconds=None,max_output_tokens=None):
        if not self.request_lock.acquire(blocking=False):
            raise AssistantError('Помощник ещё обрабатывает предыдущую просьбу. Дождитесь ответа.')
        try:
            deadline=monotonic()+deadline_seconds if deadline_seconds is not None else None
            def remaining():
                if deadline is None:return None
                value=deadline-monotonic()
                if value<=0:
                    error=AssistantError('Оформление заняло слишком много времени. Исходный текст сохранён.')
                    error.no_charge=True
                    raise error
                return value
            key,model,provider=self._credentials()
            if ((expected_provider is not None and provider!=expected_provider)
                    or (expected_model is not None and model!=expected_model)):
                raise AssistantError('Подключение помощника изменилось. Повторите просьбу.')
            paid=provider=='deepseek' or model==ai_budget.PAID_MODEL
            reservation=None
            payload = {'model': model, 'messages': messages, 'temperature': 0,
                       'max_tokens':ai_budget.PAID_OUTPUT if paid else 4000,'response_format': {'type': 'json_object'},
                       # Defence in depth: never fall back to a priced endpoint.
                       'provider': {'max_price': {'prompt': 0, 'completion': 0}, 'require_parameters': True},
                       # Some free endpoints require reasoning. Keep it small
                       # and omit its text rather than sending a disable flag.
                       'reasoning': {'effort': 'low', 'exclude': True}}
            if paid:payload['provider']['max_price']={'prompt':float(ai_budget.INPUT_PRICE),'completion':float(ai_budget.OUTPUT_PRICE)}
            # The live catalog for these explicit endpoints declares optional
            # reasoning and structured output. The random free router can pick
            # mandatory-reasoning endpoints, so it must keep the generic path.
            if response_schema is not None or model in ('nvidia/nemotron-3.5-super-vl:free','xingchen-agi/xing4.0-29b-a4b:free',ai_budget.PAID_MODEL):
                from .ai_planner import Interpretation
                schema=response_schema if response_schema is not None else Interpretation.model_json_schema()
                def compatible(value):
                    if isinstance(value,dict):
                        return {('anyOf' if k=='oneOf' else k):compatible(v) for k,v in value.items() if k!='discriminator'}
                    if isinstance(value,list):return [compatible(v) for v in value]
                    return value
                payload['response_format']={'type':'json_schema','json_schema':{'name':'dictation' if response_schema is not None else 'day_conditions','strict':True,'schema':compatible(schema)}}
                payload['reasoning']={'enabled':False}
            if provider=='deepseek':
                # Direct Chat Completions supports json_object, not OpenRouter's
                # strict response schema, routing controls or reasoning fields.
                payload={'model':ai_budget.DIRECT_MODEL,'messages':messages,'temperature':0,
                         'max_tokens':ai_budget.PAID_OUTPUT,'response_format':{'type':'json_object'},
                         'thinking':{'type':'disabled'},'stream':False}
            if max_output_tokens is not None:payload['max_tokens']=max_output_tokens
            if paid:
                remote_spent=0
                if provider=='deepseek':
                    info=self._deepseek_balance(key,timeout=remaining())
                    positive=[r for r in info['balances'] if ai_budget.usd(r['amount'])>0]
                    if not info['available'] or not positive:
                        raise AssistantError('На балансе DeepSeek API недостаточно средств. Откройте баланс в настройках и пополните его вручную.')
                    # CNY balances are shown as CNY. Do not invent an exchange
                    # rate; for them the service performs its own funds check.
                    balance=(None if any(r['currency']=='CNY' for r in positive) else
                             next((ai_budget.usd(r['amount']) for r in positive if r['currency']=='USD'),None))
                else:
                    account=self._request('GET','key',key=key,timeout=remaining()).get('data',{})
                    credits=self._request('GET','credits',key=key,timeout=remaining()).get('data',{})
                    if 'usage_monthly' not in account or 'total_credits' not in credits or 'total_usage' not in credits:
                        raise AssistantError('Не удалось проверить расходы и баланс. Платный запрос не отправлен.')
                    balance=max(ai_budget.usd(credits['total_credits'])-ai_budget.usd(credits['total_usage']),ai_budget.usd(0))
                    remote_spent=account['usage_monthly']
                with self.lock:
                    current=self._read()
                    reservation=ai_budget.reserve(current,messages,remote_spent,balance,provider_name=provider_name(provider))
                    self._write(current)
            try:
                result=self._request('POST','chat/completions',payload=payload,key=key,provider=provider,timeout=remaining())
            except Exception as exc:
                if reservation:
                    with self.lock:
                        current=self._read();ai_budget.settle(current,reservation,no_charge=getattr(exc,'no_charge',False));self._write(current)
                raise
            usage=result.get('usage') if isinstance(result.get('usage'),dict) else {}
            with self.lock:
                data = self._read()
                if reservation:
                    try:cost=(ai_budget.direct_cost(usage) if provider=='deepseek'
                              else ai_budget.usd(usage['cost']) if 'cost' in usage else None)
                    except (ValueError,TypeError,AttributeError):cost=None
                    ai_budget.settle(data,reservation,cost)
                today = datetime.now(timezone.utc).date().isoformat()
                counters = data.get('usage', {}) if data.get('usage', {}).get('date') == today else {}
                tokens=usage.get('total_tokens',0)
                if type(tokens) is not int or tokens<0:tokens=0
                data['usage']={'date':today,'requests':counters.get('requests',0)+1,
                               'tokens':counters.get('tokens',0)+tokens}
                self._write(data)
            content = None
            finish = None
            try:
                choice = result['choices'][0]
                finish = choice.get('finish_reason')
                if finish not in ('stop', None):
                    raise ValueError()
                content = choice['message']['content']
                if not isinstance(content, str):
                    raise ValueError()
                # Some models surround otherwise valid JSON with a code fence.
                if content.strip().startswith('```'):
                    content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content.strip())
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError):
                logging.warning('%s unusable JSON reply: model=%s finish=%s contentChars=%s',
                                provider_name(provider),model,str(finish)[:24],len(content) if isinstance(content,str) else 0)
                if finish=='length':
                    raise AssistantError('Модель не уложилась в размер ответа. Сократите просьбу или выберите другую модель. Расписание не изменено.') from None
                error=AssistantError('Помощник не смог точно сформулировать условия. Уточните просьбу или выберите другую модель. Расписание не изменено.')
                error.retryable=True
                raise error from None
            return parsed, str(result.get('model') or model)[:150]
        finally:
            self.request_lock.release()
