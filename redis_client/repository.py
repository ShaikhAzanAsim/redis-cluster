from functools import lru_cache

from redis.cluster import RedisCluster
from redis.exceptions import RedisError

from redis_client.cluster_client import get_cluster_client
from utils.common.custom_exceptions.record_already_exist_exception import RecordAlreadyExistException
from utils.common.custom_exceptions.record_not_found_exception import RecordNotFoundException
from utils.common.custom_exceptions.unknown_exception import UnknownException


class RedisRecordRepository:
    """Domain-facing CRUD over the Redis Cluster client.

    Callers never see redis-py or the CRC16 slot the key hashed to -- the
    underlying RedisCluster client already routes each call to the master
    that owns it. This class only translates redis-py's outcomes into the
    project's own exceptions (RecordAlreadyExistException,
    RecordNotFoundException, UnknownException).
    """

    def __init__(self, client: RedisCluster) -> None:
        self._client = client

    def add(self, key: str, value: str, ttl: int | None = None) -> None:
        try:
            created = self._client.set(key, value, nx=True, ex=ttl)
        except RedisError as exc:
            raise UnknownException(f"Failed to add record '{key}': {exc}") from exc
        if not created:
            raise RecordAlreadyExistException(f"A record with key '{key}' already exists.")

    def get(self, key: str) -> str:
        try:
            value = self._client.get(key)
        except RedisError as exc:
            raise UnknownException(f"Failed to get record '{key}': {exc}") from exc
        if value is None:
            raise RecordNotFoundException(f"No record found for key '{key}'.")
        return value

    def update(self, key: str, value: str, ttl: int | None = None) -> None:
        try:
            updated = self._client.set(key, value, xx=True, ex=ttl)
        except RedisError as exc:
            raise UnknownException(f"Failed to update record '{key}': {exc}") from exc
        if not updated:
            raise RecordNotFoundException(f"No record found for key '{key}'.")

    def delete(self, key: str) -> None:
        try:
            deleted = self._client.delete(key)
        except RedisError as exc:
            raise UnknownException(f"Failed to delete record '{key}': {exc}") from exc
        if not deleted:
            raise RecordNotFoundException(f"No record found for key '{key}'.")


@lru_cache(maxsize=1)
def get_repository() -> RedisRecordRepository:
    return RedisRecordRepository(get_cluster_client())
