import datetime
import pytest
from utils.json_util import dumps


class TestJsonDumps:
    def test_serializes_datetime(self):
        dt = datetime.datetime(2026, 1, 15, 10, 30, 0)
        result = dumps({"ts": dt})
        assert "2026-01-15T10:30:00" in result

    def test_serializes_date(self):
        d = datetime.date(2026, 6, 1)
        result = dumps({"d": d})
        assert "2026-06-01" in result

    def test_serializes_normal_types(self):
        result = dumps({"a": 1, "b": "hello", "c": [1, 2, 3], "d": None})
        assert '"a": 1' in result
        assert '"b": "hello"' in result

    def test_ensure_ascii_false_by_default(self):
        result = dumps({"msg": "你好"})
        assert "你好" in result

    def test_unknown_type_raises_type_error(self):
        class Foo:
            pass

        with pytest.raises(TypeError):
            dumps({"x": Foo()})
