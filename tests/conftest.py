import pytest

from configs.redis_cluster_config import RedisClusterConfig
from redis_client.cluster_client import get_cluster_client


@pytest.fixture(scope="session")
def cluster_config() -> RedisClusterConfig:
    return RedisClusterConfig.from_env()


@pytest.fixture(scope="session")
def cluster_client():
    client = get_cluster_client()
    yield client
    client.close()
