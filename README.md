# verseye-redis-cluster

A real, multi-master **Redis Cluster** (not just replication) running in Docker Compose, with an
env-driven Python config/client and both an automated (pytest) and interactive test suite.

New to Kubernetes, or want a cheat sheet/interview prep built from this project's own manifests?
See [`KUBERNETES_GUIDE.md`](KUBERNETES_GUIDE.md).

## Why this exists

A single Redis instance is a single point of failure and a throughput ceiling: every read and
write goes through one process, on one machine. Redis Cluster solves both problems by **sharding**
the keyspace across multiple masters (each owning a slice of the 16384 hash slots, chosen by
hashing the key with CRC16) and giving each master one or more **replicas** for failover.

This is useful whenever the data volume or write/read load a single Redis node can handle is no
longer enough, or when you can't tolerate Redis being down while a single instance restarts. The
client (`redis_client/cluster_client.py`) hides the sharding from application code entirely: you
call `.set()`/`.get()` like normal, and the client figures out which of the 3 masters actually owns
that key and talks to it directly, following redirects if the cluster ever reshapes itself (e.g.
after a failover promotes a replica to master).

This repo is a self-contained reference implementation: bring up a 9-node cluster locally, see the
sharding and failover-redirect behavior working with your own eyes (via `interactive_test.py`), and
reuse `configs/redis_cluster_config.py` + `redis_client/cluster_client.py` as the pattern for wiring
a real application up to it.

## Architecture

```
                              Redis Cluster (docker-compose, redis-cluster-net)
                              ┌───────────────────────────────────────────────┐
                              │  master 1 (slots 0-5460)                      │
                              │    ├── replica                                │
                              │    └── replica                                │
Python app / test client ───▶│  master 2 (slots 5461-10922)                  │
  picks the master owning     │    ├── replica                                │
  a key via CRC16(key)        │    └── replica                                │
  and writes/reads directly   │  master 3 (slots 10923-16383)                 │
                              │    ├── replica                                │
                              │    └── replica                                │
                              └───────────────────────────────────────────────┘
```

- **3 masters**, each owning a third of the 16384 hash slots. Redis Cluster requires >= 3 masters
  to hold a quorum vote for failover -- 1 or 2 masters is not a valid topology.
- **2 replicas per master** (9 nodes total) for high availability.
- Roles are **cluster-assigned, not fixed to a container name** -- nodes are named generically
  (`redis-node-1..9`) because after a real failover, a former replica can become a master.
- Writes always go to the owning master. A replica **never accepts a write directly** -- it
  redirects the client to its master with a `MOVED` error (see "What this proves" below).

## File guide

```
docker/
  docker-compose.yml       9 redis nodes (redis-node-1..9) + cluster-init + test-runner services,
                            static IPs on a custom bridge network, healthchecks, named volumes.
  redis/redis.conf         Shared base config for every node (cluster-enabled, AOF persistence,
                            replica-read-only). Per-node differences (announce-ip, password) are
                            passed as command overrides in docker-compose.yml.
  scripts/create-cluster.sh
                            Runs once (as the `cluster-init` service) after all 9 nodes report
                            healthy. Idempotent: checks `cluster_state:ok` first, so re-running
                            `docker compose up` against existing volumes doesn't try to recreate
                            the cluster. Otherwise runs `redis-cli --cluster create ... --cluster-replicas 2`.
  python/Dockerfile        Image used by the `test-runner` service: python:3.12-slim +
                            requirements.txt + the repo, defaults to running pytest.

configs/
  redis_config.py          Pre-existing single-node Redis config (unrelated to the cluster; left
                            untouched).
  redis_cluster_config.py  RedisClusterConfig: env-driven, frozen-dataclass config for the cluster
                            (startup nodes, password, read-from-replicas flag), following the same
                            conventions as redis_config.py (from_env(), EnvironmentNotSet on missing
                            required vars).

redis_client/
  cluster_client.py         get_cluster_client(): builds a redis-py RedisCluster client from
                            RedisClusterConfig. This is the piece that gives CRC16-slot-based write
                            routing "for free" -- it computes each key's slot, finds the owning
                            master, and sends the command there.
  repository.py             RedisRecordRepository: a thin CRUD layer over the cluster client that
                            translates redis-py's outcomes into the repo's own domain exceptions
                            (RecordAlreadyExistException, RecordNotFoundException, UnknownException)
                            instead of leaking redis-py to callers. get_repository() is its
                            lru_cache-backed singleton factory.
  __init__.py               Module-level add()/get()/update()/delete() functions delegating to
                            get_repository(), so application code just does
                            `import redis_client; redis_client.add(key, value)` -- no redis-py
                            import, no CRC16/slot/node awareness needed at the call site.

tests/
  conftest.py               pytest fixtures: cluster_config, cluster_client (session-scoped).
  test_cluster_read_write.py
                            Automated pytest suite: write/read via the cluster client, topology
                            sanity (3 masters x 2 replicas), direct replica read with/without
                            READONLY, direct replica write rejection (MovedError), direct primary
                            write.
  test_redis_record_repository.py
                            Automated pytest suite for the redis_client.add/get/update/delete
                            wrapper: round trip, duplicate add() raises RecordAlreadyExistException,
                            missing-key get()/update()/delete() raise RecordNotFoundException.

interactive_test.py         Menu-driven version of the same scenarios (press 1-7, or "a" for all)
                            that prints the key, its CRC16 slot, which node it routed to, and a
                            PASS/FAIL line for each -- for watching the behavior happen rather than
                            just seeing a pytest pass/fail summary. Option 7 exercises the
                            redis_client wrapper end to end.

requirements.txt            redis, pytest, starlette (utils/common/custom_exceptions/* use
                            starlette.status HTTP constants).
pytest.ini                  Restricts pytest collection to tests/ -- without it, pytest's default
                            `*_test.py` discovery pattern also matches interactive_test.py and tries
                            to run its menu functions as tests.
.env / .env.example         AIS_REDIS_* environment variables consumed by configs/redis_cluster_config.py
                            and by docker-compose.yml's per-node command overrides.
.dockerignore                Keeps .env, .git, __pycache__ out of the test-runner build context.
arch_diag.jpeg               Original architecture sketch this implementation is based on.

main.py, utils/common/**    Pre-existing generic scaffolding (custom exceptions, a common API
                            response envelope) from the project template; not specific to the
                            Redis cluster work.

k8s/                        Kubernetes equivalent of docker/, using a StatefulSet instead of
                            docker-compose. See "Kubernetes (StatefulSet)" below.
  00-namespace.yaml          The "redis-cluster" namespace everything else lives in.
  01-configmap-redis-conf.yaml  Same redis.conf content as docker/redis/redis.conf.
  02-secret.yaml              AIS_REDIS_PASSWORD (same dev default as .env.example).
  03-headless-service.yaml    clusterIP: None -- gives each pod a stable per-pod DNS name.
  04-statefulset.yaml         9 replicas, one PVC per pod, --cluster-announce-hostname per pod
                              via the Downward API (POD_NAME/POD_NAMESPACE).
  05-configmap-cluster-init-script.yaml / 06-job-cluster-init.yaml
                              k8s equivalent of docker/scripts/create-cluster.sh -- waits for all
                              9 pod DNS names, idempotent cluster_state:ok check, then
                              `redis-cli --cluster create`.
  07-configmap-app-env.yaml   Kubernetes equivalent of .env for the Python client (the 9 pod FQDNs
                              as AIS_REDIS_CLUSTER_NODES).
  jobs/pytest-job.yaml        k8s equivalent of `docker compose --profile test run --rm test-runner`.
                              Deliberately kept out of the flat k8s/ directory -- `kubectl apply -f
                              k8s/` is not recursive by default, so this never runs by accident
                              before the cluster has actually formed (it must run strictly after
                              06-job-cluster-init.yaml completes).

kind-cluster.yaml            Local single-node Kubernetes cluster definition (via kind) for testing
                              k8s/ on a laptop before deploying it anywhere else. Deliberately kept
                              at repo root, not under k8s/, since it's a kind CLI config, not a
                              Kubernetes resource -- `kubectl apply -f k8s/` should never see it.
```

## Prerequisites

- Docker Desktop (or a Docker Engine + Compose v2) running.

## Usage

### 1. Bring up the cluster

```
docker compose -f docker/docker-compose.yml up
```

(add `-d` to run in the background). This starts all 9 Redis nodes and, once every node reports
healthy, the one-shot `cluster-init` container creates the cluster (or, on a re-run against
existing volumes, detects it already exists and does nothing). You know it worked when you see all
9 `redis-node-*` containers as `healthy` and `redis-cluster-init` exit with code 0.

To verify from the outside at any time:

```
docker exec redis-node-1 sh -c 'redis-cli -a "$AIS_REDIS_PASSWORD" --no-auth-warning cluster info'
```

should show `cluster_state:ok`, `cluster_known_nodes:9`, `cluster_size:3`.

### 2. Run the interactive test menu

The Python client must run **inside the same docker network** as the cluster (`redis-cluster-net`)
-- the nodes announce their internal docker IPs, which aren't reachable directly from your host
machine. So the test client also runs as a docker-compose service (`test-runner`), one-off, on that
same network:

```
docker compose -f docker/docker-compose.yml build test-runner   # first time, or after editing .py files
docker compose -f docker/docker-compose.yml run --rm test-runner python interactive_test.py
```

You'll get a menu:

```
1) Write & read via cluster client (CRC16 routing demo)
2) Show cluster topology (masters/replicas, slot ranges)
3) Direct READ from a replica after READONLY -> succeeds
4) Direct READ from a replica WITHOUT READONLY -> redirected (MOVED)
5) Direct WRITE to a replica -> rejected (MOVED)
6) Direct WRITE to a primary -> succeeds
7) redis_client.add/get/update/delete wrapper demo
a) Run all of the above, in order
0) Exit
```

Each option prints the key it used, its CRC16 hash slot, which node it talked to, and a `PASS`/
`FAIL` line, so you can see exactly what happened rather than just a green checkmark.

### 3. Run the automated test suite instead (optional)

```
docker compose -f docker/docker-compose.yml --profile test run --rm test-runner
```

(the `test-runner` service defaults to `pytest -v`; it only starts under the `test` profile, so a
plain `docker compose up` never launches it).

### Shutting down

```
docker compose -f docker/docker-compose.yml down
```

Add `-v` to also delete the named volumes (wipes cluster state, so the next `up` creates a brand
new cluster from scratch instead of reusing the existing one).

## Kubernetes (StatefulSet)

`k8s/` is a from-scratch Kubernetes deployment of the *same* 3-master x 2-replica cluster, using a
`StatefulSet` instead of docker-compose. It's a separate, parallel path -- `docker/` is untouched
and still works on its own.

### Why a StatefulSet instead of docker-compose here

- **Stable per-pod identity that survives rescheduling.** docker-compose's static-IP trick only
  works because containers don't move between hosts. In Kubernetes, a pod's *IP* changes every time
  it's rescheduled, but a StatefulSet gives each pod a fixed **name** (`redis-cluster-0` ..
  `redis-cluster-8`) and, via a headless Service, a fixed **DNS name** that doesn't change --
  that's what each node announces to the rest of the cluster (`--cluster-announce-hostname`),
  instead of an IP.
- **Per-pod storage that follows the pod.** `volumeClaimTemplates` give every replica its own PVC,
  automatically re-attached to the same pod identity after a restart -- no manual volume tracking.
- **Ordered, predictable startup**, and **self-healing** -- if a node dies, Kubernetes reschedules
  it with the same name/DNS/storage automatically; docker-compose has no equivalent.
- This is the actual pattern real Redis-on-Kubernetes setups use (Bitnami's chart, the Redis
  Operator, etc.) -- not a toy simplification of it.

### Prerequisites

- `kubectl` (already installed if you have Docker Desktop -- check with `kubectl version --client`).
- [`kind`](https://kind.sigs.k8s.io/) (Kubernetes-in-Docker) for local testing -- if you don't have
  it: `winget install Kubernetes.kind` (Windows), or download the binary directly from the kind
  releases page. `kind` runs on top of your existing Docker install, nothing else to set up.
- Access to push to `harbor.qbscocloud.net:30003/verseye-project/...` (or substitute your own
  registry path throughout).

### 1. Create a local cluster to test against

```
kind create cluster --config kind-cluster.yaml
kubectl cluster-info --context kind-redis-cluster
```

This gives you a real (single-node) Kubernetes cluster running in a Docker container. Everything
from here on is standard `kubectl`, so it works identically against this local `kind` cluster or a
real one on another machine -- that's the point of doing it this way.

### 2. Build and push the test-runner image

Redis itself needs no custom image -- the StatefulSet uses the public `redis:7.4-alpine` directly.
Only the Python test/client image (`docker/python/Dockerfile`) is ours to build, and there's exactly
**one** of it (not one per node -- every pod in a StatefulSet runs the same image; what makes each
pod distinct is its ordinal name/DNS/storage, not a different image):

```
docker build -t harbor.qbscocloud.net:30003/verseye-project/verseye-redis-cluster:latest -f docker/python/Dockerfile .
docker login harbor.qbscocloud.net:30003
docker push harbor.qbscocloud.net:30003/verseye-project/verseye-redis-cluster:latest
```

If that registry needs authentication for *pulls* too (likely, for a private Harbor project), create
the image pull secret the manifests reference before applying them:

```
kubectl create namespace redis-cluster
kubectl create secret docker-registry harbor-registry-credentials \
  --docker-server=harbor.qbscocloud.net:30003 \
  --docker-username=<your-username> --docker-password=<your-password> \
  -n redis-cluster
```

(if you skip this because your registry allows anonymous pulls, just delete the `imagePullSecrets`
block from `k8s/jobs/pytest-job.yaml`.)

### 3. Apply the manifests and verify

```
kubectl apply -f k8s/
kubectl get pods -n redis-cluster -w
```

**Important:** this applies everything *except* `k8s/jobs/pytest-job.yaml` -- `kubectl apply -f k8s/`
is not recursive, so it skips the `jobs/` subdirectory on purpose. Do not run
`kubectl apply -R -f k8s/` here; the pytest Job must not start until the cluster has actually
formed (see step 4).

Wait until all 9 `redis-cluster-N` pods show `1/1 Running` and `redis-cluster-init` shows
`Completed`, then verify the cluster actually formed:

```
kubectl exec -n redis-cluster redis-cluster-0 -- sh -c 'redis-cli -a "$AIS_REDIS_PASSWORD" --no-auth-warning cluster info'
```

should show `cluster_state:ok`, `cluster_known_nodes:9`, `cluster_size:3` -- same as the
docker-compose verification. Only proceed to step 4 once you see `cluster_state:ok`.

### 4. Run the test suite

Automated (pytest), as a Job -- only after step 3 confirms `cluster_state:ok`, otherwise every test
fails with `RedisClusterException: All slots are not covered` (the client racing the cluster still
forming):

```
kubectl apply -f k8s/jobs/pytest-job.yaml
kubectl logs -n redis-cluster job/redis-cluster-pytest -f
```

If you need to rerun it (e.g. it ran too early before this fix), delete and reapply -- `kubectl
apply` on an already-existing, already-finished Job does not rerun it:

```
kubectl delete job -n redis-cluster redis-cluster-pytest
kubectl apply -f k8s/jobs/pytest-job.yaml
```

Interactive menu, as a one-off pod (mirrors `docker compose run --rm test-runner python interactive_test.py`):

```
kubectl run -n redis-cluster --rm -it redis-cluster-manual \
  --image=harbor.qbscocloud.net:30003/verseye-project/verseye-redis-cluster:latest \
  --restart=Never \
  --overrides='{"spec":{"imagePullSecrets":[{"name":"harbor-registry-credentials"}],"containers":[{"name":"redis-cluster-manual","image":"harbor.qbscocloud.net:30003/verseye-project/verseye-redis-cluster:latest","stdin":true,"tty":true,"command":["python","interactive_test.py"],"envFrom":[{"configMapRef":{"name":"redis-app-env"}},{"secretRef":{"name":"redis-secret"}}]}]}}'
```

Same menu, same output shape as the docker-compose version.

### Teardown

```
kubectl delete namespace redis-cluster   # removes everything in k8s/, keeps the kind cluster
kind delete cluster --name redis-cluster # or tear down the whole local cluster
```

### Deploying on another PC

Nothing here is laptop-specific: `k8s/*.yaml` are plain Kubernetes manifests and the image lives in
your registry, so on another machine (with `kubectl` pointed at whatever cluster you're using
there, `kind` or otherwise) steps 3-4 above are all that's needed -- no rebuild required unless the
code changed.

## Application-facing API

Application code should never import redis-py or `redis_client.cluster_client` directly -- it
should call the module-level wrapper instead:

```python
import redis_client

redis_client.add("user:42", "some-value")     # raises RecordAlreadyExistException if it exists
value = redis_client.get("user:42")            # raises RecordNotFoundException if missing
redis_client.update("user:42", "new-value")    # raises RecordNotFoundException if missing
redis_client.delete("user:42")                 # raises RecordNotFoundException if missing
```

No key hashing, slot lookup, or node selection happens at the call site -- that's entirely handled
by the underlying `RedisCluster` client. `add()` is insert-only (backed by an atomic `SET ... NX`,
so there's no check-then-set race), not an upsert; use `update()` to overwrite an existing key. Any
underlying redis-py/connection error (timeouts, cluster-down, etc.) is translated into
`UnknownException` rather than propagating raw redis-py exceptions -- so callers only ever need to
handle the three exceptions in `utils/common/custom_exceptions/`.

## What this proves

The scenario the user requirements centered on -- "if someone tries to write directly to a
replica's address, it must fail" -- is real Redis Cluster behavior, not something bolted on here: a
replica owns no hash slots itself, so any write sent straight to it comes back as a `MOVED`
redirect to the owning master instead of being applied. `interactive_test.py` option `5` (and
`tests/test_cluster_read_write.py::test_direct_write_to_replica_is_rejected`) demonstrate this
directly against a live replica container.
