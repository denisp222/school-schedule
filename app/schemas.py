"""Input validation with messages suitable for the school office."""
from pydantic import TypeAdapter, StrictInt, ValidationError

_integer = TypeAdapter(StrictInt)
FIELD_BOUNDS={'maxDays':(1,5),'maxDaily':(1,12),'weeklyTarget':(0,60),'size':(0,100),
              'firstPeriod':(1,7),'capacity':(0,300),'difficulty':(1,12)}


def field_integer(field,value,label):
    lower,upper=FIELD_BOUNDS[field]
    return integer(value,label,minimum=lower,maximum=upper)


def integer(value, label, *, minimum=None, maximum=None):
    try:
        if isinstance(value, str) and value.strip().isdigit():value = int(value.strip())
        result = _integer.validate_python(value)
        if minimum is not None and result < minimum or maximum is not None and result > maximum:raise ValueError()
        return result
    except (ValueError, TypeError, ValidationError):
        raise ValueError(f'{label}: укажите целое число' + (f' от {minimum} до {maximum}.' if minimum is not None and maximum is not None else '.')) from None
