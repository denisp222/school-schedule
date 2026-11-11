"""Conservative local monthly budget, including unknown in-flight charges."""
from decimal import Decimal, InvalidOperation, ROUND_UP
from datetime import datetime, timezone
from uuid import uuid4
import json
from time import time

PAID_MODEL='deepseek/deepseek-v4.1-flash-1017'
DIRECT_MODEL='deepseek-flash'
# Official DeepSeek Flash peak USD prices, checked 2026-11-07.
# We deliberately count at peak prices even during cheaper off-peak hours.
CACHE_PRICE=Decimal('0.006')
INPUT_PRICE=Decimal('0.30')
OUTPUT_PRICE=Decimal('1.20')
PAID_OUTPUT=6000
RESERVATION_TTL=600


def usd(value):
    try:
        result=Decimal(str(value))
        if not result.is_finite() or result<0:raise ValueError()
        return result
    except (InvalidOperation,ValueError,TypeError):
        raise ValueError('Не удалось прочитать стоимость запроса. Платный вызов не выполнен.') from None


def month():return datetime.now(timezone.utc).strftime('%Y-%m')


def ledger(data):
    value=data.get('billing',{})
    value=value if value.get('month')==month() else {'month':month(),'spent':'0','remoteSpent':'0','reservations':{}}
    timestamps=value.setdefault('reservationTimes',{})
    # An abandoned call may have reached the provider. Expire the in-flight
    # marker into conservative spend, rather than silently refunding money.
    for token,amount in list(value.get('reservations',{}).items()):
        if time()-timestamps.get(token,0)<RESERVATION_TTL:continue
        value['spent']=str(usd(value.get('spent',0))+usd(amount))
        value['reservations'].pop(token)
        timestamps.pop(token,None)
        value.setdefault('expiredReservations',{})[token]=amount
    # At most a small bounded reconciliation window is needed.
    while len(value.get('expiredReservations',{}))>1000:
        value['expiredReservations'].pop(next(iter(value['expiredReservations'])))
    return value


def summary(data):
    row=ledger(data)
    held=sum((usd(v) for v in row.get('reservations',{}).values()),Decimal(0))
    spent=max(usd(row.get('spent',0)),usd(row.get('remoteSpent',0)))+held
    return {'month':row['month'],'spentUSD':str(spent),'limitUSD':str(usd(data.get('monthlyLimitUSD','1')))}


def estimate(messages):
    # A UTF-8 byte bounds text token count; extra space covers role framing.
    size=len(json.dumps(messages,ensure_ascii=False).encode('utf-8'))+16384
    return ((Decimal(size)*INPUT_PRICE+Decimal(PAID_OUTPUT)*OUTPUT_PRICE)/Decimal(1_000_000)).quantize(Decimal('.000001'),rounding=ROUND_UP)


def reserve(data,messages,remote_spent,balance,*,provider_name='OpenRouter'):
    value=ledger(data);value['remoteSpent']=str(usd(remote_spent))
    amount=estimate(messages)
    held=sum((usd(v) for v in value.get('reservations',{}).values()),Decimal(0))
    spent=max(usd(value.get('spent',0)),usd(value['remoteSpent']))
    if spent+held+amount>usd(data.get('monthlyLimitUSD','1')):
        raise ValueError('Достигнут месячный предел расходов помощника. Новый платный запрос не отправлен.')
    if balance is not None and usd(balance)<amount:
        raise ValueError(f'На балансе {provider_name} недостаточно средств. Откройте баланс в настройках и пополните его вручную.')
    token=uuid4().hex
    # Carry the remote floor forward before adding this call. Otherwise a
    # lagging remote counter could hide several new local charges below it.
    value['spent']=str(spent)
    value.setdefault('reservations',{})[token]=str(amount);data['billing']=value
    value.setdefault('reservationTimes',{})[token]=time()
    return token


def direct_cost(usage):
    """Upper USD estimate from official token counters; None means hold reserve."""
    prompt=usage.get('prompt_tokens');output=usage.get('completion_tokens')
    if any(type(n) is not int or n<0 for n in (prompt,output)):return None
    hit=usage.get('prompt_cache_hit_tokens',usage.get('prompt_tokens_details',{}).get('cached_tokens',0))
    if type(hit) is not int or not 0<=hit<=prompt:return None
    miss=usage.get('prompt_cache_miss_tokens',prompt-hit)
    if type(miss) is not int or hit+miss!=prompt:return None
    return ((Decimal(miss)*INPUT_PRICE+Decimal(hit)*CACHE_PRICE+Decimal(output)*OUTPUT_PRICE)/Decimal(1_000_000)).quantize(Decimal('.000001'),rounding=ROUND_UP)


def settle(data,token,cost=None,*,no_charge=False):
    value=ledger(data);held=value.setdefault('reservations',{}).pop(token,None)
    value.setdefault('reservationTimes',{}).pop(token,None)
    if held is None:
        held=value.setdefault('expiredReservations',{}).pop(token,None)
        if held is not None:value['spent']=str(max(Decimal(0),usd(value.get('spent',0))-usd(held)))
    if held is None:return
    charged=Decimal(0) if no_charge else usd(cost) if cost is not None else usd(held)
    value['spent']=str(usd(value.get('spent',0))+charged);data['billing']=value
