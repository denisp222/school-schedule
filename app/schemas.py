"""Input validation with messages suitable for the school office."""
from pydantic import TypeAdapter, StrictInt, ValidationError

_integer = TypeAdapter(StrictInt)


def integer(value, label, *, minimum=None, maximum=None):
    try:
        if isinstance(value, str) and value.strip().isdigit():value = int(value.strip())
        result = _integer.validate_python(value)
        if minimum is not None and result < minimum or maximum is not None and result > maximum:raise ValueError()
        return result
    except (ValueError, TypeError, ValidationError):
        raise ValueError(f'{label}: укажите целое число' + (f' от {minimum} до {maximum}.' if minimum is not None and maximum is not None else '.')) from None
