#!/bin/bash
# One-line remote-node init.
# Run on a freshly-flashed Pi after rpi-imager has set hostname / WiFi / user / ssh-key:
#   curl -fsL --retry 20 --retry-delay 5 https://raw.githubusercontent.com/jmorris0x0/bass-sentry/master/bootstrap.sh -o /tmp/bs.sh && bash /tmp/bs.sh pi-1.json
set -euo pipefail

DAG=${1:?usage: bootstrap.sh <dag_file, e.g. pi-1.json>}
REPO_URL=https://github.com/jmorris0x0/bass-sentry.git
REPO_DIR=$HOME/bass-sentry
SENTINEL=$HOME/.bass-bootstrap-done

# Wait for real connectivity before doing anything. systemd's
# network-online.target can fire before DNS resolves or before the
# default route is fully installed, so we probe github.com directly.
until curl -fsS --max-time 5 -o /dev/null https://github.com; do
  echo "Bootstrap: waiting for network to reach github.com..."
  sleep 5
done

# Loop apt-get in case another apt process holds the lock at boot.
until sudo apt-get update -y; do
  echo "Bootstrap: apt-get update failed, retrying in 10s..."
  sleep 10
done
until sudo apt-get install -y git portaudio19-dev python3-venv python3-pip; do
  echo "Bootstrap: apt-get install failed, retrying in 10s..."
  sleep 10
done

if [ ! -d "$REPO_DIR" ]; then
  until git clone "$REPO_URL" "$REPO_DIR"; do
    echo "Bootstrap: git clone failed, retrying in 10s..."
    sleep 10
  done
fi

cd "$REPO_DIR"
git pull --ff-only || true

if [ ! -f "remote-node/dag_files/$DAG" ]; then
  echo "DAG file remote-node/dag_files/$DAG not found" >&2
  exit 1
fi

./remote-node-setup.sh "$DAG"

# Only mark bootstrap done AFTER a full successful run. Prior version
# had the sentinel touched by ExecStartPost, which fired even when the
# curl pipe silently failed and bash ran an empty script.
touch "$SENTINEL"
echo "Bootstrap: complete."
