import time
import uuid

import pytest
import redis
from redis.cluster import ClusterNode
from redis.exceptions import MovedError


def _direct_client(cluster_config, node: ClusterNode) -> redis.Redis:
    return redis.Redis(
        host=node.host,
        port=node.port,
        password=cluster_config.password,
        decode_responses=True,
    )


def test_write_then_read_via_cluster(cluster_client):
    """Sanity check: the cluster client can write and read keys, wherever the
    CRC16 hash slot happens to route them."""
    for i in range(10):
        key = f"test:rw:{uuid.uuid4()}"
        value = f"value-{i}"
        assert cluster_client.set(key, value)
        assert cluster_client.get(key) == value


def test_topology_has_three_primaries_with_two_replicas_each(cluster_client):
    assert len(cluster_client.get_primaries()) == 3
    assert len(cluster_client.get_replicas()) == 6


def test_direct_read_from_replica_succeeds(cluster_client, cluster_config):
    """A replica only serves a slot's data locally to connections that have
    opted in via READONLY (see test below for what happens without it)."""
    key = f"test:replica-read:{uuid.uuid4()}"
    value = "replica-read-value"
    cluster_client.set(key, value)

    replica_node = cluster_client.get_node_from_key(key, replica=True)
    replica = _direct_client(cluster_config, replica_node)
    try:
        replica.readonly()
        for _ in range(20):
            if replica.get(key) == value:
                break
            time.sleep(0.1)
        else:
            pytest.fail("value did not replicate to the replica in time")
    finally:
        replica.close()


def test_direct_read_from_replica_without_readonly_is_redirected(cluster_client, cluster_config):
    """Without READONLY, a replica redirects every command (including reads)
    to its master via MOVED -- a replica never serves cluster traffic on its
    own behalf."""
    key = f"test:replica-no-readonly:{uuid.uuid4()}"
    cluster_client.set(key, "value")

    replica_node = cluster_client.get_node_from_key(key, replica=True)
    replica = _direct_client(cluster_config, replica_node)
    try:
        with pytest.raises(MovedError):
            replica.get(key)
    finally:
        replica.close()


def test_direct_write_to_replica_is_rejected(cluster_client, cluster_config):
    """The core requirement: writing straight to a replica's address must be
    refused. In cluster mode a replica owns no slots itself, so it always
    redirects writes to its master via MOVED -- regardless of READONLY --
    rather than serving them."""
    key = f"test:replica-write:{uuid.uuid4()}"
    replica_node = cluster_client.get_node_from_key(key, replica=True)

    replica = _direct_client(cluster_config, replica_node)
    try:
        replica.readonly()
        with pytest.raises(MovedError):
            replica.set(key, "should-not-be-written")
    finally:
        replica.close()


def test_direct_write_to_primary_succeeds(cluster_client, cluster_config):
    key = f"test:primary-write:{uuid.uuid4()}"
    primary_node = cluster_client.get_node_from_key(key)

    primary = _direct_client(cluster_config, primary_node)
    try:
        assert primary.set(key, "ok")
        assert primary.get(key) == "ok"
    finally:
        primary.close()
