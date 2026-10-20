from redis_client.repository import get_repository


def add(key: str, value: str, ttl: int | None = None) -> None:
    get_repository().add(key, value, ttl=ttl)


def get(key: str) -> str:
    return get_repository().get(key)


def update(key: str, value: str, ttl: int | None = None) -> None:
    get_repository().update(key, value, ttl=ttl)


def delete(key: str) -> None:
    get_repository().delete(key)
