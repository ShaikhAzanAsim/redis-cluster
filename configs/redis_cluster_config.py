import os
from dataclasses import dataclass

from utils.common.custom_exceptions.environment_not_set import EnvironmentNotSet


def _str_to_bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class RedisClusterConfig:
    nodes: str
    password: str
    read_from_replicas: bool
    logs_limit: int

    def __init__(
        self,
        nodes: str | None = None,
        password: str | None = None,
        read_from_replicas: bool | str | None = None,
        logs_limit: int | str | None = None,
    ) -> None:
        if nodes is None or nodes == "":
            raise EnvironmentNotSet("AIS_REDIS_CLUSTER_NODES is required")
        if password is None:
            raise EnvironmentNotSet("AIS_REDIS_PASSWORD is required")

        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "password", password)
        object.__setattr__(
            self,
            "read_from_replicas",
            read_from_replicas
            if isinstance(read_from_replicas, bool)
            else _str_to_bool(read_from_replicas or "true"),
        )
        object.__setattr__(self, "logs_limit", int(logs_limit or 50))

    @property
    def startup_nodes(self) -> list[tuple[str, int]]:
        pairs = []
        for entry in self.nodes.split(","):
            host, port = entry.strip().split(":")
            pairs.append((host, int(port)))
        return pairs

    @classmethod
    def from_env(cls) -> "RedisClusterConfig":
        return cls(
            nodes=os.getenv("AIS_REDIS_CLUSTER_NODES", ""),
            password=os.getenv("AIS_REDIS_PASSWORD", "Verseye!23"),
            read_from_replicas=os.getenv("AIS_REDIS_CLUSTER_READ_FROM_REPLICAS", "true"),
            logs_limit=os.getenv("AIS_REDIS_LOGS_LIMIT", "50"),
        )
