import json

from src.execution.adapter import redact, redact_obj


def test_redacts_json_token():
    assert json.loads(redact('{"token": "abc123"}'))["token"] == "[REDACTED]"


def test_redacts_bearer_value():
    assert redact("Bearer secretstring") == "Bearer [REDACTED]"


def test_redacts_url_userinfo_and_sensitive_query():
    value = redact("https://user:pass@host:8787/path?token=xyz")
    assert value == "https://host:8787/path?token=[REDACTED]"


def test_redacts_mixed_case_inline_secret():
    assert redact("ApiKey=XYZsecret") == "ApiKey=[REDACTED]"


def test_redacts_nested_object_without_mutating_public_values():
    value = {"outer": [{"Secret": "hidden", "public": "shown"}]}
    assert redact_obj(value) == {
        "outer": [{"Secret": "[REDACTED]", "public": "shown"}]
    }


def test_short_inline_secret_is_left_alone():
    assert redact("pw=x") == "pw=x"
