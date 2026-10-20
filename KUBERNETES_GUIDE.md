# Kubernetes Guide, Cheat Sheet & Interview Prep

A from-first-principles Kubernetes reference, taught through the actual objects in `k8s/` in this
repo. Every concept below points at a real file/line you already have running, plus a cheat sheet,
multi-PC ("bare metal") cluster setup, real failure modes with fixes (including three we hit
ourselves this project), interview Q&A, and a Helm primer.

**Table of contents**
1. [Beginner: core concepts](#1-beginner-core-concepts)
2. [Intermediate: networking, scheduling, config](#2-intermediate-networking-scheduling-config)
3. [Advanced: multi-node clusters, HA, storage, scaling](#3-advanced-multi-node-clusters-ha-storage-scaling)
4. [This project, mapped file-by-file](#4-this-project-mapped-file-by-file)
5. [kubectl cheat sheet](#5-kubectl-cheat-sheet)
6. [Real deployment problems & solutions](#6-real-deployment-problems--solutions)
7. [Helm: what it is, and where this project goes next](#7-helm-what-it-is-and-where-this-project-goes-next)
8. [Interview Q&A](#8-interview-qa)

---

## 1. Beginner: core concepts

### The problem Kubernetes solves

You have containers (Docker images). Running one container on one machine is easy (`docker run`).
The hard problems start at scale: *which machine runs which container, what happens when a machine
or container dies, how do containers find each other, how do you roll out a new version without
downtime, how do you give a container storage that survives a restart.* Kubernetes is a system that
answers all of those questions declaratively: you describe the **desired state** ("I want 9 Redis
pods, each with 1Gi of storage"), and a set of **controllers** continuously reconcile reality
towards that desired state. This is the single most important mental model in Kubernetes:
**you never imperatively tell it what to do -- you declare what should exist, and something else
makes it true, forever, in a loop.**

### Cluster shape: control plane vs nodes

A cluster is one or more **control plane** machines (the "brain") and one or more **worker nodes**
(where your containers actually run).

Control plane components (usually you never touch these directly):
- **kube-apiserver** -- the only thing anything talks to. Every `kubectl` command is an HTTP call
  to this. It validates and stores objects.
- **etcd** -- the distributed key-value store that's the actual source of truth for the entire
  cluster's state (every object you `kubectl apply`d lives here).
- **kube-scheduler** -- decides *which node* a new Pod should run on, based on resource requests,
  affinity rules, taints, etc.
- **kube-controller-manager** -- runs the reconciliation loops (the "Deployment controller",
  "Job controller", "StatefulSet controller", etc. -- these are what actually create/delete Pods to
  match your desired state).

Worker node components (run on every node that hosts your workloads):
- **kubelet** -- the agent on each node that talks to the apiserver and actually starts/stops
  containers via the container runtime.
- **kube-proxy** -- programs the node's networking rules so Services (see below) work.
- **container runtime** -- containerd/CRI-O/Docker -- actually runs the containers.

You saw this split directly: `kind create cluster --config kind-cluster.yaml` (in this repo) spins
up one machine that plays *both* roles (control-plane + worker) inside a single Docker container --
that's why it's called "Kubernetes-in-Docker." A real multi-PC setup (Section 3) is the same
architecture spread across real machines.

### The core objects, in the order you actually learn them

| Object | What it is | Where you've used it |
|---|---|---|
| **Pod** | The smallest deployable unit -- one or more containers that always run together, on the same node, sharing one IP. Pods are disposable; you almost never create one directly. | `k8s/04-statefulset.yaml`'s `template:` is a Pod template |
| **Namespace** | A virtual sub-cluster for grouping/isolating objects by name. | `k8s/00-namespace.yaml` -- everything else lives in `redis-cluster` |
| **Deployment** | Manages a set of *identical, interchangeable* Pod replicas (stateless apps: web servers, APIs). Rolling updates, self-healing. | Not used here on purpose -- see StatefulSet below |
| **StatefulSet** | Manages Pods that need a **stable identity** (name, network, storage) -- databases, brokers, anything clustered. | `k8s/04-statefulset.yaml` |
| **DaemonSet** | Runs exactly one Pod per node (log collectors, node monitoring agents). | Not used in this project |
| **Job / CronJob** | Runs a Pod to completion once (Job) or on a schedule (CronJob), instead of forever. | `k8s/06-job-cluster-init.yaml`, `k8s/jobs/pytest-job.yaml` |
| **Service** | A stable virtual IP/DNS name in front of a changing set of Pods. | `k8s/03-headless-service.yaml` |
| **ConfigMap** | Non-secret configuration data, injectable as env vars or mounted files. | `k8s/01-configmap-redis-conf.yaml`, `k8s/07-configmap-app-env.yaml` |
| **Secret** | Same idea as ConfigMap, but for sensitive data (base64-encoded at rest, not encrypted by default -- see Section 6). | `k8s/02-secret.yaml` |
| **PersistentVolume (PV) / PersistentVolumeClaim (PVC)** | A PVC is a Pod's *request* for storage ("give me 1Gi, ReadWriteOnce"); a PV is the actual storage that fulfills it (provisioned dynamically by a `StorageClass` in almost every real cluster). | `volumeClaimTemplates` in `k8s/04-statefulset.yaml` -- each of the 9 pods gets its own PVC (`data-redis-cluster-0` .. `data-redis-cluster-8`) |

### Labels & selectors

Nearly everything in Kubernetes is wired together by string key/value **labels**, matched by
**selectors** -- there's no other kind of "reference." In this repo:
`k8s/03-headless-service.yaml`'s `selector: app: redis-cluster` finds every Pod with label
`app: redis-cluster` -- which is exactly the label set on the StatefulSet's Pod template in
`k8s/04-statefulset.yaml`. Change one without the other and the Service silently stops finding any
Pods (a very common real bug -- see Section 6).

---

## 2. Intermediate: networking, scheduling, config

### Cluster networking model

Every Pod gets its own IP, from a flat network where (in principle) every Pod can reach every other
Pod directly, no NAT -- this is a hard Kubernetes networking requirement, implemented by a **CNI
plugin** (Flannel, Calico, Cilium, etc.) that you install once per cluster. Pod IPs are **ephemeral**
-- they change every time a Pod is rescheduled. This is *the* central problem a StatefulSet-based
system like ours has to solve (see below).

### Services: how Pods find each other

A **Service** is a stable name/IP in front of a *set* of Pods (chosen by label selector). Types:
- `ClusterIP` (default) -- one stable internal IP, load-balanced across matching Pods. Not used
  here, because our client doesn't need one -- see next point.
- `Headless` (`clusterIP: None`) -- **no load-balancing IP at all.** Instead, DNS returns one A
  record *per matching Pod*, and (critically for a StatefulSet) each Pod also gets its own
  individually addressable DNS name: `<pod-name>.<service-name>.<namespace>.svc.cluster.local`.
  This is exactly `k8s/03-headless-service.yaml` -- it's what makes `redis-cluster-0.redis-cluster-headless.redis-cluster.svc.cluster.local`
  a real, resolvable, stable address.
- `NodePort` -- opens the same port on every node, forwarding into the cluster. Cheap way to expose
  something outside the cluster in a bare-metal/kind setup with no cloud load balancer.
- `LoadBalancer` -- asks the cloud provider (AWS/GCP/Azure) to provision a real external load
  balancer. Meaningless on kind/bare-metal without an add-on like MetalLB.

### The pod-IP-churn problem, and how this project solves it

Pod IPs change on every reschedule. Redis Cluster nodes need to announce *some* address to each
other so they can gossip and clients can follow `MOVED` redirects. Two different fixes, matched to
two different orchestrators, both in this repo:
- **docker-compose** (`docker/docker-compose.yml`): containers don't move between hosts, so a
  **static IP** per container is stable enough. Each node passes `--cluster-announce-ip <its static
  IP>`.
- **Kubernetes** (`k8s/04-statefulset.yaml`): Pod IPs are *not* stable, but the **Pod's name and DNS
  name are**, via the StatefulSet + headless Service combo above. So instead of announcing an IP,
  each node announces its own hostname: `--cluster-announce-hostname
  "$(POD_NAME).redis-cluster-headless.$(POD_NAMESPACE).svc.cluster.local" --cluster-preferred-endpoint-type hostname`
  (Redis 7+ feature). `POD_NAME`/`POD_NAMESPACE` come from the **Downward API** -- a way to inject
  a Pod's own metadata into itself as env vars, without hardcoding it per-replica:
  ```yaml
  env:
    - name: POD_NAME
      valueFrom: { fieldRef: { fieldPath: metadata.name } }
  ```
  This is *the* generalizable lesson: **whenever you need a clustered/stateful workload on
  Kubernetes, the pattern is always StatefulSet + headless Service + hostname-based (not
  IP-based) self-identification.**

### DNS in Kubernetes

CoreDNS runs as a cluster add-on and answers `*.svc.cluster.local` queries. Any Pod can resolve
`<service>.<namespace>.svc.cluster.local` (or bare `<service>` if querying from the same
namespace) to reach a Service. Headless Services additionally publish per-Pod DNS records, as
above. When you see a `RedisClusterException`/`NXDOMAIN`/timeout that looks networking-related,
DNS resolution failing *inside* the cluster is one of the first things to check (Section 6).

### Probes: how Kubernetes knows a Pod is healthy

- **readinessProbe** -- "can this Pod serve traffic *right now*?" If it fails, the Pod is pulled out
  of a Service's endpoints (no traffic sent to it) but *not* restarted.
- **livenessProbe** -- "is this Pod fundamentally broken?" If it fails repeatedly, Kubernetes kills
  and restarts the container.
- **startupProbe** -- like liveness, but only active during slow startup, so you don't need a huge
  `initialDelaySeconds` on the liveness probe for a slow-booting app.

In `k8s/04-statefulset.yaml`, both probes run the exact same check:
`redis-cli -a "$AIS_REDIS_PASSWORD" --no-auth-warning ping | grep -q PONG` -- an `exec` probe (runs a
command inside the container), as opposed to `httpGet` or `tcpSocket` probes used for web services.

### Resource requests & limits

`resources.requests` (set in `k8s/04-statefulset.yaml`: `cpu: 100m, memory: 128Mi`) is what the
scheduler uses to decide *which node has room* for this Pod -- it's a reservation, not a cap.
`resources.limits` (not set here, deliberately kept lean for a demo) is a hard ceiling -- exceed the
memory limit and the container gets **OOMKilled**; exceed the CPU limit and it gets throttled, not
killed. Every Pod's `requests` vs `limits` combination gives it a **QoS class** (`Guaranteed`,
`Burstable`, `BestEffort`) which affects eviction order under node pressure.

### ConfigMap & Secret: two ways to consume them

Either as **environment variables** (`envFrom: configMapRef/secretRef`, used throughout this
project's Jobs, e.g. `k8s/jobs/pytest-job.yaml`) or as **mounted files** (`volumes: configMap:`,
used for `redis.conf` itself in `k8s/04-statefulset.yaml` via `subPath: redis.conf`, and for the
cluster-init shell script in `k8s/06-job-cluster-init.yaml`). Rule of thumb: config a program reads
from env vars at startup -> env var injection; config that's a whole file the program expects at a
path (a `.conf` file, a script) -> volume mount.

---

## 3. Advanced: multi-node clusters, HA, storage, scaling

### Setting this up across multiple real PCs (not kind)

This is the "multiple PCs acting as masters and slaves" scenario you asked about -- with one
important terminology clash to clear up first:

> **"Master/slave" means two completely different things here, and it's easy to conflate them:**
> 1. **Kubernetes control-plane node ("master") vs worker node** -- which *machines* run the
>    Kubernetes brain vs which run your workloads. This is a cluster-infrastructure concept.
> 2. **Redis master vs replica** -- which *Pods* (wherever they happen to be scheduled) own a slot
>    range vs replicate it. This is an *application-level* concept, entirely inside the Redis
>    Cluster you built, and has nothing to do with which physical PC each Pod landed on.
>
> A Redis master Pod can be scheduled on a Kubernetes worker node, which itself is not a Kubernetes
> control-plane "master" at all. Don't let the shared word confuse the two layers.

**The standard tool for a real multi-PC cluster is `kubeadm`** (what `kind` uses internally,
minus the Docker-in-Docker wrapping):

1. **Prerequisites, on every PC:** same container runtime (containerd), swap disabled
   (`swapoff -a` + remove from `/etc/fstab` -- kubelet refuses to start with swap on), required
   kernel modules/sysctls for networking (`br_netfilter`, `net.ipv4.ip_forward=1`), open the right
   ports between machines (`6443` apiserver, `2379-2380` etcd on control-plane nodes,
   `10250` kubelet, `10251`/`10252` scheduler/controller-manager, `30000-32767` for NodePort
   Services, `179`/`4789`/etc. depending on your CNI plugin).
2. **On the first PC (control-plane):** `kubeadm init --pod-network-cidr=<range>` -- this bootstraps
   etcd, the apiserver, scheduler, controller-manager, and prints a `kubeadm join ...` command with
   a join token.
3. **Install a CNI plugin** (Calico, Flannel, Cilium...) on the control-plane -- until you do, nodes
   stay `NotReady` because there's no Pod networking yet.
4. **On every other PC (workers):** run the `kubeadm join ...` command it printed. Each one starts a
   `kubelet` that registers itself with the control-plane's apiserver.
5. **Verify:** `kubectl get nodes` from the control-plane machine (or any machine with its
   kubeconfig) should list all PCs, `STATUS Ready`.
6. **Now schedule this project's manifests as-is** -- `kubectl apply -f k8s/` works completely
   unchanged; the scheduler will now spread the 9 Redis pods across your real PCs instead of a
   single kind node.

### High availability of the control plane itself

One control-plane PC is a single point of failure for the *whole cluster* (not just your app --
if it dies, `kubectl` stops working and no new Pods get scheduled anywhere, though already-running
Pods keep running). Real HA setups run **3 (or 5) control-plane machines**, because etcd uses Raft
consensus and needs an odd-numbered majority quorum to keep accepting writes -- exactly the same
"why 3, not 2, masters" reasoning you already internalized for Redis Cluster in this project
(`README.md`'s architecture section). A load balancer (or a `kube-vip`-style floating IP) sits in
front of the API servers so `kubectl`/kubelets always have one address to talk to regardless of
which control-plane machine is up.

### Scheduling controls: where Pods actually land

- **nodeSelector / nodeAffinity** -- "only run this Pod on nodes matching label X" (e.g., only
  nodes with fast local SSDs for the Redis pods).
- **podAffinity / podAntiAffinity** -- "run this Pod near/away from other Pods." For real HA, you'd
  add a `podAntiAffinity` rule so the 3 Redis masters (and their replicas) are never scheduled onto
  the same physical PC -- otherwise losing one machine could take out a master *and* its replica
  simultaneously, defeating the whole point of replication. (This project's kind cluster is
  single-node, so this doesn't apply yet -- it's the first thing to add when you move to real
  multi-PC hardware.)
- **topologySpreadConstraints** -- a more general "spread evenly across zones/nodes" mechanism.
- **taints & tolerations** -- the inverse of affinity: a *node* repels Pods unless a Pod explicitly
  "tolerates" it (e.g., control-plane nodes are tainted `node-role.kubernetes.io/control-plane:NoSchedule`
  by default, which is *why* your workloads never land on them).

### Storage across multiple real nodes

`kind`'s default `StorageClass` (`local-path-provisioner`) creates storage **on whichever single
node** the Pod landed on -- fine for a one-node test cluster, but on real multiple PCs this becomes
a trap: if a Pod with local storage gets rescheduled to a *different* PC, its old data is left
behind on the original machine and inaccessible. For a real multi-PC deployment you need
network-attached or replicated storage so a PVC can be reattached no matter which node the Pod
moves to: **NFS** (simplest), **Longhorn** or **Rook/Ceph** (replicated block storage,
Kubernetes-native), or a cloud provider's disk service if you're not on bare metal.

### Autoscaling

- **HPA (Horizontal Pod Autoscaler)** -- adds/removes replicas of a Deployment based on
  CPU/memory/custom metrics. (Not meaningful for a fixed-shard StatefulSet like Redis Cluster --
  you can't just "add a replica" of a stateful shard without a resharding operation.)
- **VPA (Vertical Pod Autoscaler)** -- adjusts a Pod's resource requests/limits automatically.
- **Cluster Autoscaler** -- adds/removes whole *nodes* (PCs/VMs) based on whether Pods are Pending
  for lack of room.

### Observability

`metrics-server` (lightweight, powers `kubectl top`) for basic CPU/memory; Prometheus + Grafana for
real dashboards/alerting; `kubectl logs`/a log-shipping DaemonSet (Fluent Bit, etc.) for
centralized logs across many nodes -- essential once you have more than a couple of PCs and can't
just `kubectl logs` your way through debugging.

---

## 4. This project, mapped file-by-file

| File | Kubernetes object | Concept it teaches |
|---|---|---|
| `k8s/00-namespace.yaml` | Namespace | Isolating a group of related objects |
| `k8s/01-configmap-redis-conf.yaml` | ConfigMap | Non-secret config as a mounted file |
| `k8s/02-secret.yaml` | Secret | Sensitive config, `stringData` convenience field |
| `k8s/03-headless-service.yaml` | Service (`clusterIP: None`) | Stable per-pod DNS instead of load-balancing |
| `k8s/04-statefulset.yaml` | StatefulSet | Stable identity, `volumeClaimTemplates`, Downward API, probes, `podManagementPolicy` |
| `k8s/05-configmap-cluster-init-script.yaml` | ConfigMap | Mounting a script as an executable file (`defaultMode`) |
| `k8s/06-job-cluster-init.yaml` | Job | Run-to-completion workload, `backoffLimit`, `restartPolicy: OnFailure` |
| `k8s/07-configmap-app-env.yaml` | ConfigMap | Env-var injection for an external client |
| `k8s/jobs/pytest-job.yaml` | Job | `restartPolicy: Never`, `imagePullSecrets`, why it's kept out of the non-recursive `kubectl apply -f k8s/` sweep |
| `kind-cluster.yaml` | (kind CLI config, not a k8s object) | Local single-node cluster + private-registry containerd mirror config |

---

## 5. kubectl cheat sheet

```bash
# Context / cluster
kubectl config get-contexts               # list known clusters
kubectl config use-context kind-redis-cluster
kubectl cluster-info

# Everyday reads
kubectl get pods -n redis-cluster                       # list
kubectl get pods -n redis-cluster -o wide               # + node, IP
kubectl get pods -n redis-cluster -w                    # watch (live updates)
kubectl get all -n redis-cluster                         # pods, services, jobs, etc. at once
kubectl describe pod redis-cluster-0 -n redis-cluster    # events + full spec (first place to look when something's wrong)
kubectl logs redis-cluster-0 -n redis-cluster             # container logs
kubectl logs redis-cluster-0 -n redis-cluster -f          # follow
kubectl logs job/redis-cluster-pytest -n redis-cluster    # logs of a Job's pod

# Getting inside
kubectl exec -it redis-cluster-0 -n redis-cluster -- sh
kubectl exec -n redis-cluster redis-cluster-0 -- redis-cli -a "$PASS" ping

# Applying / removing
kubectl apply -f k8s/                     # create/update everything in a directory (non-recursive)
kubectl apply -R -f k8s/                  # recursive -- careful, see Section 6 pitfall
kubectl delete -f k8s/08-job-pytest.yaml
kubectl delete job -n redis-cluster redis-cluster-pytest  # Jobs must be deleted before reapplying to rerun
kubectl delete namespace redis-cluster    # nuke everything in one shot

# Debugging
kubectl get events -n redis-cluster --sort-by=.lastTimestamp
kubectl top pods -n redis-cluster         # needs metrics-server
kubectl get pods -n redis-cluster -o yaml # full resolved spec, incl. defaults you didn't set

# StatefulSet-specific
kubectl get statefulset -n redis-cluster
kubectl rollout status statefulset/redis-cluster -n redis-cluster
kubectl rollout restart statefulset/redis-cluster -n redis-cluster

# Scaling
kubectl scale statefulset redis-cluster -n redis-cluster --replicas=6

# Secrets / registries
kubectl create secret docker-registry harbor-registry-credentials \
  --docker-server=harbor.qbscocloud.net:30003 \
  --docker-username=<user> --docker-password=<pass> -n redis-cluster
kubectl create secret generic my-secret --from-literal=KEY=value -n redis-cluster

# Nodes (multi-PC cluster)
kubectl get nodes -o wide
kubectl describe node <node-name>
kubectl cordon <node-name>      # stop scheduling new Pods here (before maintenance)
kubectl drain <node-name>       # evict existing Pods elsewhere, then cordon
kubectl uncordon <node-name>
```

---

## 6. Real deployment problems & solutions

Three of these are things **you personally hit in this project** -- kept first since they're the
most concrete.

1. **"`kubectl apply -f k8s/` ran the pytest Job before the cluster had formed"** (this project,
   verbatim). Cause: `kubectl apply -f <dir>` applies *every* file in that directory in one shot,
   with no ordering/dependency awareness between unrelated objects -- a Job has no concept of
   "wait for that other Job to finish first." Fix used here: move the dependent Job into a
   subdirectory (`k8s/jobs/`) so the non-recursive default `kubectl apply -f k8s/` never picks it
   up automatically; apply it explicitly, later, once you've confirmed readiness. (The general
   version of this fix for a *real* pipeline is a CI step that polls/waits, or a Helm post-install
   hook -- see Section 7.)

2. **"Deleted a Job and reapplied the same YAML, but it didn't rerun"** (also hit here). Jobs are
   immutable once created for most fields; `kubectl apply` on an unchanged, already-completed Job
   is a no-op. Fix: `kubectl delete job <name>` first, then `kubectl apply` again (exactly what we
   did to get `redis-cluster-pytest` to actually rerun after the cluster became healthy).

3. **"Private registry image pull fails"** (this project's Harbor registry). Two independent things
   both have to be true: (a) the *cluster's container runtime* must be able to reach/trust the
   registry (for `kind`, the `containerdConfigPatches` block in `kind-cluster.yaml`), and (b) if the
   registry requires auth, every Pod that pulls from it needs an `imagePullSecret`
   (`kubectl create secret docker-registry ...`, referenced in `k8s/jobs/pytest-job.yaml`).
   Missing either shows up as `ImagePullBackOff`/`ErrImagePull` in `kubectl describe pod`.

4. **`CrashLoopBackOff`** -- the container starts, then exits (crashes or the main process finishes)
   repeatedly, with an exponential backoff between restarts. Almost always: bad config/missing env
   var causing the app to exit immediately, wrong command, or the readiness/liveness probe killing
   it before it's actually ready. First move: `kubectl logs <pod> --previous` (logs from the *last*
   crashed attempt, since the current one may not have logged anything yet).

5. **`Pending` pod, never scheduled.** `kubectl describe pod` will show the scheduler's exact
   reason in the Events section -- almost always one of: no node has enough free CPU/memory for the
   `requests`, a `PersistentVolumeClaim` is stuck unbound (no StorageClass/provisioner available),
   or a taint on every node isn't tolerated.

6. **`OOMKilled`** -- the container exceeded its memory `limit` and was killed by the kernel. Fix:
   raise the limit, or find/fix the actual leak; check `kubectl describe pod` for
   `Last State: Terminated, Reason: OOMKilled`.

7. **PVC stuck `Pending` forever.** No `StorageClass` exists, or it exists but no provisioner is
   running to actually create storage for it (common on bare-metal clusters that don't have
   Longhorn/Rook/NFS-provisioner installed -- `kind` and cloud providers set this up for you
   automatically, a fresh `kubeadm` cluster does not).

8. **DNS resolution fails inside the cluster** (a Pod can't reach
   `some-service.namespace.svc.cluster.local`). Check CoreDNS is actually running
   (`kubectl get pods -n kube-system -l k8s-app=kube-dns`), check the Service's label `selector`
   actually matches the target Pods' labels (the single most common real-world cause -- a typo'd
   label silently means "matches nothing," not an error), and remember a headless Service's
   per-pod DNS records only appear once that specific Pod is up and has an IP.

9. **StatefulSet Pod stuck `Terminating` forever.** Common when its PVC or the storage backend is
   unhealthy, or a `finalizer` is blocking deletion. `kubectl get pod <name> -o yaml | grep
   finalizers` to see what's holding it; force-delete (`kubectl delete pod <name> --grace-period=0
   --force`) is a last resort that can leave orphaned state -- understand *why* it's stuck before
   reaching for this.

10. **etcd/control-plane quorum loss** (multi-master HA setups only): if you lose more than
    `(N-1)/2` control-plane nodes (e.g., 2 of 3), etcd can no longer commit writes -- the cluster
    goes read-only for its own state (existing Pods keep running, but nothing can be
    created/updated/deleted, including via `kubectl`). This is exactly why an odd number >= 3 is
    used, mirroring the "why Redis Cluster needs >= 3 masters" reasoning in this repo's main
    `README.md`.

11. **Node shows `NotReady`.** kubelet on that node stopped reporting in (crashed, network
    partition, or the node itself is down). Its Pods get rescheduled elsewhere automatically after a
    grace period (`kubectl describe node` shows the last heartbeat) -- but if that node had
    `local` storage-backed Pods, see the storage section above: the *data* doesn't move with them.

12. **Config change didn't take effect after `kubectl apply` on a ConfigMap.** Pods that consume a
    ConfigMap as env vars (like every Job in this project) do **not** automatically pick up changes
    -- env vars are injected once, at container start. Only volume-mounted ConfigMaps update live
    (with a delay), and even then the *application inside* usually needs to notice the file changed
    and reload itself. Practical fix: `kubectl rollout restart` (Deployment/StatefulSet) or
    delete+reapply (Job) after changing a ConfigMap/Secret.

---

## 7. Helm: what it is, and where this project goes next

Straight from what your coworker described, made concrete:

**The problem Helm solves.** You have `app -> Docker image -> Kubernetes manifests`. That's exactly
what `k8s/` in this repo is -- 10 hand-written YAML files for *one* app. Now imagine N
microservices that all follow the same shape (a Deployment/StatefulSet + a Service + a ConfigMap +
a Secret, just with a different image tag, replica count, and a few env vars each). Copy-pasting
and hand-editing `N x (number of files)` YAML files is exactly the "N x 3 config files" problem your
coworker described. **Helm is a templating engine + package manager for Kubernetes manifests**: you
write the YAML *once*, as a template with `{{ .Values.xyz }}` placeholders, and supply the
differences per-deployment in one small `values.yaml` file.

**Chart anatomy:**
```
my-chart/
  Chart.yaml          # name, version, description of the chart itself
  values.yaml          # the *default* configuration values (replica count, image tag, etc.)
  templates/
    statefulset.yaml    # same YAML you already have, but with {{ .Values... }} placeholders
    service.yaml
    configmap.yaml
    secret.yaml
    _helpers.tpl        # reusable template snippets (naming conventions, labels)
  charts/               # sub-charts / dependencies (rare, for this scale)
```

**Concretely, what `k8s/04-statefulset.yaml` becomes as a Helm template** (illustrative excerpt):
```yaml
spec:
  replicas: {{ .Values.replicaCount }}
  template:
    spec:
      containers:
        - name: redis
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          resources:
            requests:
              cpu: {{ .Values.resources.requests.cpu }}
              memory: {{ .Values.resources.requests.memory }}
```
and `values.yaml` holds the one place you change per-environment:
```yaml
replicaCount: 9
image:
  repository: harbor.qbscocloud.net:30003/verseye-project/verseye-redis-cluster
  tag: latest
resources:
  requests: { cpu: 100m, memory: 128Mi }
```

**Deploying N microservices that share this shape** then becomes: one generic chart, and one small
`values-<service>.yaml` per microservice (or one chart per service, sharing a common
library-chart for the repeated bits) -- deployed with one command each instead of hand-tracking
every YAML file:
```bash
helm install redis-cluster ./my-chart -f values-redis-cluster.yaml
helm install other-service ./my-chart -f values-other-service.yaml
```

**Helm cheat sheet:**
```bash
helm create my-chart                 # scaffold a new chart
helm install <release-name> ./chart  # first deploy ("release")
helm upgrade <release-name> ./chart  # deploy a changed chart/values over an existing release
helm upgrade --install <name> ./chart  # install if new, upgrade if it exists (the common CI pattern)
helm rollback <release-name> <revision>  # instant revert to a previous release revision
helm list -n redis-cluster            # what releases exist in a namespace
helm uninstall <release-name>
helm template ./chart                 # render the YAML locally without applying -- great for debugging
helm lint ./chart                     # catch template mistakes before deploying
helm show values ./chart              # see all configurable values
```

**Where this repo would go next if you converted it to a chart:** `k8s/*.yaml` move into
`chart/templates/`, every hardcoded value (`replicas: 9`, the Harbor image path, the password
default, storage size) becomes a `{{ .Values.* }}` reference, and the awkward "don't apply
`k8s/jobs/pytest-job.yaml` too early" ordering problem from Section 6 gets a *real* fix: Helm
supports **hooks** (`helm.sh/hook: post-install`) plus **hook weights**, so you can declare "this Job
runs after the StatefulSet is up," instead of relying on a human remembering the right order and
directory layout.

---

## 8. Interview Q&A

### Beginner

**Q: What is a Pod, and why not just run containers directly?**
A: A Pod is the smallest unit Kubernetes schedules -- one or more containers that always share a
network namespace (one IP) and can share volumes. You don't run bare containers because Kubernetes
needs *something* it can attach identity, networking, storage, and lifecycle (restart policy,
health checks) to as a single schedulable unit; a Pod is that unit.

**Q: What's the difference between a Deployment and a StatefulSet?**
A: A Deployment manages interchangeable, identical replicas with no individual identity -- any
replica can be killed and replaced by a fresh one with a new name/IP, fine for stateless services.
A StatefulSet gives each replica a stable name (`-0`, `-1`, ...), a stable per-pod DNS name (via a
headless Service), and its own persistent volume that follows it across restarts -- required for
anything clustered/stateful (databases, Kafka, Redis Cluster, as in this project).

**Q: ConfigMap vs Secret?**
A: Same mechanism, different intent: Secret is for sensitive values. By default a Secret is only
base64-*encoded* in etcd, not encrypted -- base64 is an encoding, not encryption, so anyone with
etcd or API access can trivially decode it unless you've enabled encryption-at-rest and RBAC
properly. Don't rely on "it's a Secret" alone for real security.

**Q: What does a Service actually do?**
A: Provides a stable virtual IP/DNS name that load-balances to a changing set of Pods, selected by
label, so callers never need to track individual Pod IPs (which are ephemeral).

### Intermediate

**Q: Walk me through what happens when you `kubectl apply` a Deployment.**
A: `kubectl` sends the object to the apiserver, which validates and persists it to etcd. The
Deployment controller (in kube-controller-manager) notices the desired state changed and creates/
updates a ReplicaSet, which creates the requested number of Pod objects. The scheduler assigns each
unscheduled Pod to a node based on resource requests/affinity/taints. Each node's kubelet notices a
Pod was assigned to it and asks the container runtime to actually start the containers.

**Q: How does a headless Service differ from a normal one, and why would you use it?**
A: A normal (ClusterIP) Service gives you one virtual IP that load-balances across matching Pods --
you can't address a specific Pod through it. A headless Service (`clusterIP: None`) instead gives
DNS entries for every individual matching Pod, and for Pods that are part of a StatefulSet, a
stable per-pod name. You use it whenever clients (or the Pods themselves, like Redis Cluster
gossip) need to address a *specific* member, not "any one of the pool."

**Q: Explain readiness vs liveness probes and what happens if you get them backwards.**
A: Readiness gates whether a Pod receives traffic (fail = removed from Service endpoints, Pod
keeps running); liveness gates whether the Pod gets restarted (fail repeatedly = kubelet kills and
restarts the container). If you use a slow/expensive check as a liveness probe, a temporarily slow
dependency can cause a restart *loop* that makes the outage worse, not better -- that check usually
belongs in readiness instead, or behind a `startupProbe` grace period.

**Q: How does DNS resolution work for a Service?**
A: CoreDNS runs as cluster Pods and watches the apiserver for Service/Endpoint objects. It answers
`<service>.<namespace>.svc.cluster.local` with the Service's ClusterIP (or, for a headless Service,
the individual Pod IPs / per-pod names). Every Pod's `/etc/resolv.conf` is configured to query
CoreDNS and search the local namespace by default.

### Advanced

**Q: How would you design a highly available Kubernetes control plane, and why an odd number of
nodes?**
A: Run 3 (or 5) control-plane nodes, each with its own etcd member, fronted by a load balancer (or
a floating VIP) so clients always have one address regardless of which node is up. etcd uses Raft
consensus, which needs a strict majority (`> N/2`) of members alive to keep accepting writes -- an
even number adds a node without adding fault tolerance (losing 2 of 4 is just as fatal as losing 2
of 3, but you paid for a 4th machine for nothing), which is why 3 or 5, never 4, matching exactly
the "why does Redis Cluster need >= 3 masters" quorum logic.

**Q: You have a stateful clustered application (Redis, Kafka, a database). Why StatefulSet over
Deployment, in detail?**
A: Three concrete reasons: (1) cluster membership/gossip needs a *stable* identity per node --
Deployment Pods get a new random name/IP on every restart, which breaks any protocol that remembers
"node X is at address Y"; (2) each replica typically owns its own non-interchangeable data (a shard,
a partition) -- Deployment's `volumeClaimTemplates`-equivalent doesn't exist, all replicas would
share one PVC; StatefulSet gives each ordinal its own PVC that reattaches to the same identity after
a restart; (3) ordered, one-at-a-time startup/shutdown matters for join/leave protocols in a way a
Deployment's parallel rollout doesn't guarantee (though `podManagementPolicy: Parallel`, used in
this project, opts back into parallel starts when the app can tolerate it, as symmetric
not-yet-clustered Redis nodes can).

**Q: A Pod can't resolve another Service's DNS name. Debug it.**
A: Check, in order: (1) is CoreDNS itself running and healthy (`kubectl get pods -n kube-system`);
(2) does the target Service actually exist and does its label `selector` match at least one Pod's
labels (`kubectl get endpoints <service>` -- empty endpoints means the selector matches nothing,
the most common real cause and *not* a DNS problem at all); (3) is the querying Pod in a NetworkPolicy-
restricted namespace that blocks DNS (port 53) egress; (4) for a headless Service's per-pod name
specifically, is *that exact Pod* currently Running with an assigned IP.

**Q: How would you actually spread a Redis Cluster's masters and replicas across separate physical
machines for real fault tolerance, and why doesn't this project's kind setup do it?**
A: Add `podAntiAffinity` (or `topologySpreadConstraints`) rules keyed on `app: redis-cluster` with
`topologyKey: kubernetes.io/hostname`, so the scheduler refuses to place two Pods that would defeat
replication (e.g. a master and its own replica) on the same physical node. This project's `kind`
cluster is a single node, so there's nothing to spread across yet -- this is precisely the first
change to make when moving from the local kind cluster to real multiple PCs (Section 3).

**Q: What's the difference between Helm and just writing raw YAML, and when would you reach for
Kustomize instead?**
A: Helm is a full templating language (Go templates) plus a package/release model (install,
upgrade, rollback, versioned releases) -- best when you have real parameterization needs across many
near-identical deployments (exactly the "N microservices, same shape" problem). Kustomize is
patch-based, not templated: you keep a full "base" set of plain YAML and layer small
`kustomization.yaml` patches per environment (dev/staging/prod) on top, with no new templating
syntax to learn -- often preferred when the differences between environments are small and you
want to avoid a templating language inside YAML (a common source of hard-to-read charts).

**Q: Tell me about a Kubernetes project you've built.**
A (worked example, using this repo): "I converted a docker-compose-based 3-master/2-replica-per-
master Redis Cluster into a Kubernetes StatefulSet. The core problem was that docker-compose's
static-IP trick for cluster gossip doesn't work in Kubernetes because Pod IPs churn on reschedule,
so I used a headless Service plus Redis 7's `--cluster-announce-hostname`, populated per-pod via the
Downward API, so each node announces its stable DNS name instead of an IP. Cluster bootstrap is an
idempotent Job that polls all 9 pod DNS names and only runs `redis-cli --cluster create` if the
cluster isn't already formed. I hit a real ordering bug where `kubectl apply -f k8s/` applied a
dependent test Job before the cluster had finished forming, which I fixed by moving that Job out of
the default (non-recursive) apply path and documenting the explicit two-step sequence -- and then
verified 13 automated tests pass against the live cluster to confirm it."

---

*See `README.md` for the docker-compose and Kubernetes run/verify instructions this guide
references throughout.*
