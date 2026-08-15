from dataclasses import dataclass

import pytest

from serena_skill_cli.mcp_client import _normalize_result


@dataclass
class FakeResult:
    data: dict

    def model_dump(self, **_kwargs):
        return self.data


def test_normalize_single_json_text():
    result = FakeResult({"content": [{"type": "text", "text": '{"value":1}'}], "isError": False})
    assert _normalize_result(result) == {"value": 1}


def test_normalize_single_plain_text():
    result = FakeResult({"content": [{"type": "text", "text": "OK"}]})
    assert _normalize_result(result) == "OK"


def test_normalize_error_raises():
    with pytest.raises(RuntimeError):
        _normalize_result(FakeResult({"isError": True, "content": []}))
