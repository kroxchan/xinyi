"""Tests for src/exceptions.py."""
from __future__ import annotations

from src.exceptions import (
    XinyiBaseError,
    APIClientError,
    MemoryExtractionError,
    DecryptionError,
    ConfigError,
    RerankError,
    exc_to_user_msg,
)


def test_xinyi_base_error_with_hint():
    err = XinyiBaseError("something broke", hint="try again")
    assert "something broke" in str(err)
    assert err.hint == "try again"


def test_api_client_error():
    err = APIClientError("connection refused", status_code=503, is_retryable=True)
    assert err.status_code == 503
    assert err.is_retryable is True
    assert "检查" in err.hint


def test_memory_extraction_error_insufficient_data():
    err = MemoryExtractionError("no beliefs extracted", reason="insufficient_data")
    assert err.reason == "insufficient_data"
    assert "30 条" in err.hint or "对话量" in err.hint


def test_decryption_error_xcode_missing():
    err = DecryptionError("xcode not found", reason="xcode_missing")
    assert "xcode" in err.hint.lower()


def test_exc_to_user_msg_known_exception():
    err = MemoryExtractionError("no data", reason="insufficient_data")
    msg = exc_to_user_msg(err)
    assert len(msg) > 5


def test_exc_to_user_msg_unknown_exception():
    msg = exc_to_user_msg(ValueError("bad value"))
    assert len(msg) > 0
    assert "ValueError" in msg or "操作失败" in msg
