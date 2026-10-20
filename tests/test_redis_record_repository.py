import uuid

import pytest

import redis_client
from utils.common.custom_exceptions.record_already_exist_exception import RecordAlreadyExistException
from utils.common.custom_exceptions.record_not_found_exception import RecordNotFoundException


def _key(prefix: str) -> str:
    return f"test:repo:{prefix}:{uuid.uuid4()}"


def test_add_then_get_round_trip():
    key = _key("add-get")
    redis_client.add(key, "value-1")
    assert redis_client.get(key) == "value-1"


def test_add_duplicate_raises_record_already_exist():
    key = _key("dup")
    redis_client.add(key, "value-1")
    with pytest.raises(RecordAlreadyExistException):
        redis_client.add(key, "value-2")
    assert redis_client.get(key) == "value-1"


def test_get_missing_key_raises_record_not_found():
    key = _key("missing-get")
    with pytest.raises(RecordNotFoundException):
        redis_client.get(key)


def test_update_existing_key():
    key = _key("update")
    redis_client.add(key, "value-1")
    redis_client.update(key, "value-2")
    assert redis_client.get(key) == "value-2"


def test_update_missing_key_raises_record_not_found():
    key = _key("missing-update")
    with pytest.raises(RecordNotFoundException):
        redis_client.update(key, "value-1")


def test_delete_existing_key():
    key = _key("delete")
    redis_client.add(key, "value-1")
    redis_client.delete(key)
    with pytest.raises(RecordNotFoundException):
        redis_client.get(key)


def test_delete_missing_key_raises_record_not_found():
    key = _key("missing-delete")
    with pytest.raises(RecordNotFoundException):
        redis_client.delete(key)
