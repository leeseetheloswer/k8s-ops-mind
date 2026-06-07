import datetime


def _default(obj):
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def dumps(obj, **kwargs) -> str:
    import json
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(obj, default=_default, **kwargs)
