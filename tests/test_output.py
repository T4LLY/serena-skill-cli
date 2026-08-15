import json

from serena_skill_cli.output import envelope, render


def test_compact_json_is_default():
    text = render(envelope(ok=True, result={"a": 1}))
    assert "\n" not in text
    assert json.loads(text)["result"]["a"] == 1
