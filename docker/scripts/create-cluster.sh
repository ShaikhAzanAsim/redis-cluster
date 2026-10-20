#!/bin/sh
set -eu

NODES="172.30.0.11:6379 172.30.0.12:6379 172.30.0.13:6379 172.30.0.14:6379 172.30.0.15:6379 172.30.0.16:6379 172.30.0.17:6379 172.30.0.18:6379 172.30.0.19:6379"
FIRST_HOST=172.30.0.11
FIRST_PORT=6379

redis_cli() {
  redis-cli -a "$AIS_REDIS_PASSWORD" --no-auth-warning "$@"
}

echo "Waiting for ${FIRST_HOST}:${FIRST_PORT} to accept connections..."
until redis_cli -h "$FIRST_HOST" -p "$FIRST_PORT" ping >/dev/null 2>&1; do
  sleep 1
done

if redis_cli -h "$FIRST_HOST" -p "$FIRST_PORT" cluster info | grep -q "cluster_state:ok"; then
  echo "Cluster already initialized, skipping creation."
  exit 0
fi

echo "Creating cluster: 3 masters x 2 replicas"
redis_cli --cluster create $NODES --cluster-replicas 2 --cluster-yes
