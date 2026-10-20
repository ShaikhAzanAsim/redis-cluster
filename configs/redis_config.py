import os
from dataclasses import dataclass

from utils.common.custom_exceptions.environment_not_set import EnvironmentNotSet


@dataclass(frozen=True)
class RedisConfig:
    host: str
    port: int
    password: str
    db: int
    logs_limit: int

    def __init__(
        self,
        host: str | None = None,
        port: int | str | None = None,
        password: str | None = None,
        db: int | str | None = None,
        logs_limit: int | str | None = None,
    ) -> None:
        if host is None or host == "":
            raise EnvironmentNotSet("AIS_REDIS_HOST is required")
        if password is None:
            raise EnvironmentNotSet("AIS_REDIS_PASSWORD is required")

        object.__setattr__(self, "host", host)
        object.__setattr__(self, "port", int(port or 6379))
        object.__setattr__(self, "password", password)
        object.__setattr__(self, "db", int(db or 0))
        object.__setattr__(self, "logs_limit", int(logs_limit or 50))

    @classmethod
    def from_env(cls) -> "RedisConfig":
        return cls(
            host=os.getenv("AIS_REDIS_HOST", "localhost"),
            port=os.getenv("AIS_REDIS_PORT", "6379"),
            password=os.getenv("AIS_REDIS_PASSWORD", "Verseye!23"),
            db=os.getenv("AIS_REDIS_DB", "0"),
            logs_limit=os.getenv("AIS_REDIS_LOGS_LIMIT", "50"),
        )
