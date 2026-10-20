from functools import lru_cache

from redis.cluster import ClusterNode, LoadBalancingStrategy, RedisCluster

from configs.redis_cluster_config import RedisClusterConfig


def _build_startup_nodes(config: RedisClusterConfig) -> list[ClusterNode]:
    return [ClusterNode(host=host, port=port) for host, port in config.startup_nodes]


@lru_cache(maxsize=1)
def get_cluster_client() -> RedisCluster:
    config = RedisClusterConfig.from_env()
    return RedisCluster(
        startup_nodes=_build_startup_nodes(config),
        password=config.password,
        load_balancing_strategy=(
            LoadBalancingStrategy.ROUND_ROBIN_REPLICAS if config.read_from_replicas else None
        ),
        decode_responses=True,
    )
