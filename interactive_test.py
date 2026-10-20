"""
Interactive, menu-driven exercise of the Redis Cluster.

Run after the cluster is up (`docker compose -f docker/docker-compose.yml up`):

    docker compose -f docker/docker-compose.yml run --rm test-runner python interactive_test.py

This must run inside the `redis-cluster-net` docker network (via the
test-runner service) -- the cluster nodes announce their internal docker IPs,
which aren't reachable from the host machine directly. It exercises the same
scenarios as tests/test_cluster_read_write.py, but one at a time, with the
key/slot/node/exception details printed so you can see exactly what happened.
"""

import uuid

import redis
from redis.cluster import ClusterNode
from redis.crc import key_slot
from redis.exceptions import MovedError

import redis_client
from configs.redis_cluster_config import RedisClusterConfig
from redis_client.cluster_client import get_cluster_client
from utils.common.custom_exceptions.record_already_exist_exception import RecordAlreadyExistException
from utils.common.custom_exceptions.record_not_found_exception import RecordNotFoundException

SEPARATOR = "-" * 70


def _direct_client(config: RedisClusterConfig, node: ClusterNode) -> redis.Redis:
    return redis.Redis(
        host=node.host,
        port=node.port,
        password=config.password,
        decode_responses=True,
    )


def _print_node(label: str, node: ClusterNode) -> None:
    print(f"{label}: {node.host}:{node.port} ({node.server_type})")


def _pass(message: str) -> None:
    print(f"PASS -- {message}")


def _fail(message: str) -> None:
    print(f"FAIL -- {message}")


def show_topology(client: redis.cluster.RedisCluster) -> None:
    print(SEPARATOR)
    print("Cluster topology (CLUSTER NODES)")
    print(SEPARATOR)
    nodes = client.cluster_nodes()
    masters = {addr: info for addr, info in nodes.items() if "master" in info["flags"]}
    for addr, info in sorted(masters.items()):
        slots = ", ".join(f"{lo}-{hi}" for lo, hi in info["slots"]) or "(no slots)"
        print(f"master {addr}  id={info['node_id'][:8]}  slots={slots}")
        replicas = {a: i for a, i in nodes.items() if i["master_id"] == info["node_id"]}
        for r_addr, r_info in sorted(replicas.items()):
            print(f"  replica {r_addr}  id={r_info['node_id'][:8]}")
    print(f"\ntotal nodes: {len(nodes)}  masters: {len(masters)}  replicas: {len(nodes) - len(masters)}")


def test_1_write_read_via_cluster(client: redis.cluster.RedisCluster, config: RedisClusterConfig) -> None:
    print(SEPARATOR)
    print("Test 1: write & read via the cluster client (CRC16 slot routing)")
    print(SEPARATOR)
    ok = True
    for i in range(5):
        key = f"test:rw:{uuid.uuid4()}"
        value = f"value-{i}"
        slot = key_slot(key.encode())
        primary = client.get_node_from_key(key)
        client.set(key, value)
        readback = client.get(key)
        print(f"key={key}  slot={slot}  routed_to={primary.host}:{primary.port}  wrote={value!r}  read={readback!r}")
        if readback != value:
            ok = False
    _pass("all keys round-tripped correctly") if ok else _fail("a readback did not match what was written")


def test_2_topology(client: redis.cluster.RedisCluster) -> None:
    print(SEPARATOR)
    print("Test 2: topology sanity (3 masters x 2 replicas)")
    print(SEPARATOR)
    show_topology(client)
    primaries = client.get_primaries()
    replicas = client.get_replicas()
    if len(primaries) == 3 and len(replicas) == 6:
        _pass(f"found {len(primaries)} masters and {len(replicas)} replicas")
    else:
        _fail(f"expected 3 masters / 6 replicas, got {len(primaries)} masters / {len(replicas)} replicas")


def test_3_replica_read_with_readonly(client: redis.cluster.RedisCluster, config: RedisClusterConfig) -> None:
    print(SEPARATOR)
    print("Test 3: direct READ from a replica after sending READONLY -> should succeed")
    print(SEPARATOR)
    key = f"test:replica-read:{uuid.uuid4()}"
    value = "replica-read-value"
    slot = key_slot(key.encode())
    client.set(key, value)
    replica_node = client.get_node_from_key(key, replica=True)
    print(f"key={key}  slot={slot}  wrote via cluster client: {value!r}")
    _print_node("connecting directly to replica", replica_node)

    conn = _direct_client(config, replica_node)
    try:
        conn.readonly()
        print("sent READONLY on this connection")
        readback = conn.get(key)
        print(f"GET {key} -> {readback!r}")
        if readback == value:
            _pass("replica served the read locally after READONLY")
        else:
            _fail(f"expected {value!r}, got {readback!r} (replication may not have caught up yet)")
    except Exception as exc:
        _fail(f"unexpected exception: {type(exc).__name__}: {exc}")
    finally:
        conn.close()


def test_4_replica_read_without_readonly(client: redis.cluster.RedisCluster, config: RedisClusterConfig) -> None:
    print(SEPARATOR)
    print("Test 4: direct READ from a replica WITHOUT READONLY -> should be redirected (MOVED)")
    print(SEPARATOR)
    key = f"test:replica-no-readonly:{uuid.uuid4()}"
    slot = key_slot(key.encode())
    client.set(key, "value")
    replica_node = client.get_node_from_key(key, replica=True)
    primary_node = client.get_node_from_key(key)
    print(f"key={key}  slot={slot}")
    _print_node("owning master", primary_node)
    _print_node("connecting directly to replica (no READONLY)", replica_node)

    conn = _direct_client(config, replica_node)
    try:
        conn.get(key)
        _fail("expected a MovedError but the GET succeeded")
    except MovedError as exc:
        print(f"GET raised MovedError: {exc}")
        _pass("replica redirected the read to its master, as expected")
    except Exception as exc:
        _fail(f"expected MovedError, got {type(exc).__name__}: {exc}")
    finally:
        conn.close()


def test_5_replica_write_rejected(client: redis.cluster.RedisCluster, config: RedisClusterConfig) -> None:
    print(SEPARATOR)
    print("Test 5: direct WRITE to a replica -> should be rejected (MOVED to its master)")
    print(SEPARATOR)
    key = f"test:replica-write:{uuid.uuid4()}"
    slot = key_slot(key.encode())
    replica_node = client.get_node_from_key(key, replica=True)
    primary_node = client.get_node_from_key(key)
    print(f"key={key}  slot={slot}")
    _print_node("owning master", primary_node)
    _print_node("connecting directly to replica", replica_node)

    conn = _direct_client(config, replica_node)
    try:
        conn.readonly()
        conn.set(key, "should-not-be-written")
        _fail("expected a MovedError but the SET succeeded")
    except MovedError as exc:
        print(f"SET raised MovedError: {exc}")
        _pass("replica refused the write and redirected to its master, as expected")
    except Exception as exc:
        _fail(f"expected MovedError, got {type(exc).__name__}: {exc}")
    finally:
        conn.close()


def test_6_primary_write_succeeds(client: redis.cluster.RedisCluster, config: RedisClusterConfig) -> None:
    print(SEPARATOR)
    print("Test 6: direct WRITE to a primary -> should succeed")
    print(SEPARATOR)
    key = f"test:primary-write:{uuid.uuid4()}"
    slot = key_slot(key.encode())
    primary_node = client.get_node_from_key(key)
    print(f"key={key}  slot={slot}")
    _print_node("connecting directly to primary", primary_node)

    conn = _direct_client(config, primary_node)
    try:
        conn.set(key, "ok")
        readback = conn.get(key)
        print(f"SET/GET -> {readback!r}")
        if readback == "ok":
            _pass("primary accepted the write directly")
        else:
            _fail(f"unexpected readback: {readback!r}")
    except Exception as exc:
        _fail(f"unexpected exception: {type(exc).__name__}: {exc}")
    finally:
        conn.close()


def test_7_repository_wrapper(client: redis.cluster.RedisCluster, config: RedisClusterConfig) -> None:
    print(SEPARATOR)
    print("Test 7: redis_client.add/get/update/delete wrapper (no CRC16/node handling by the caller)")
    print(SEPARATOR)
    key = f"test:repo:{uuid.uuid4()}"

    redis_client.add(key, "first-value")
    print(f"redis_client.add({key!r}, 'first-value') -> OK")

    try:
        redis_client.add(key, "second-value")
        _fail("expected RecordAlreadyExistException on duplicate add() but it succeeded")
        return
    except RecordAlreadyExistException as exc:
        print(f"redis_client.add({key!r}, 'second-value') again -> RecordAlreadyExistException: {exc}")

    value = redis_client.get(key)
    print(f"redis_client.get({key!r}) -> {value!r}")
    if value != "first-value":
        _fail(f"expected 'first-value', got {value!r}")
        return

    redis_client.update(key, "updated-value")
    value = redis_client.get(key)
    print(f"redis_client.update({key!r}, 'updated-value'); get -> {value!r}")
    if value != "updated-value":
        _fail(f"expected 'updated-value', got {value!r}")
        return

    redis_client.delete(key)
    print(f"redis_client.delete({key!r}) -> OK")

    try:
        redis_client.get(key)
        _fail("expected RecordNotFoundException after delete() but get() succeeded")
        return
    except RecordNotFoundException as exc:
        print(f"redis_client.get({key!r}) after delete -> RecordNotFoundException: {exc}")

    _pass("add/get/update/delete and both domain exceptions behaved as expected")


MENU = {
    "1": ("Write & read via cluster client (CRC16 routing demo)", test_1_write_read_via_cluster),
    "2": ("Show cluster topology (masters/replicas, slot ranges)", test_2_topology),
    "3": ("Direct READ from a replica after READONLY -> succeeds", test_3_replica_read_with_readonly),
    "4": ("Direct READ from a replica WITHOUT READONLY -> redirected (MOVED)", test_4_replica_read_without_readonly),
    "5": ("Direct WRITE to a replica -> rejected (MOVED)", test_5_replica_write_rejected),
    "6": ("Direct WRITE to a primary -> succeeds", test_6_primary_write_succeeds),
    "7": ("redis_client.add/get/update/delete wrapper demo", test_7_repository_wrapper),
}


def run(choice: str, client: redis.cluster.RedisCluster, config: RedisClusterConfig) -> None:
    if choice == "2":
        test_2_topology(client)
    else:
        MENU[choice][1](client, config)
    print()


def main() -> None:
    config = RedisClusterConfig.from_env()
    client = get_cluster_client()

    print(SEPARATOR)
    print("Redis Cluster interactive test menu")
    print(f"Startup nodes: {config.nodes}")
    print(SEPARATOR)

    while True:
        print()
        for key, (description, _) in MENU.items():
            print(f"  {key}) {description}")
        print("  a) Run all of the above, in order")
        print("  0) Exit")
        choice = input("\nChoice: ").strip().lower()

        if choice in ("0", "q", "quit", "exit"):
            break
        if choice == "a":
            for key in MENU:
                run(key, client, config)
            continue
        if choice in MENU:
            run(choice, client, config)
        else:
            print(f"Unknown option: {choice!r}")

    client.close()


if __name__ == "__main__":
    main()
