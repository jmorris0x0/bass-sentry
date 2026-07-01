#!/bin/bash
# One-line remote-node init.
# Run on a freshly-flashed Pi after rpi-imager has set hostname / WiFi / user / ssh-key:
#   curl -sfL https://raw.githubusercontent.com/jmorris0x0/bass-sentry/master/bootstrap.sh | bash -s pi-1.json
set -euo pipefail

DAG=${1:?usage: bootstrap.sh <dag_file, e.g. pi-1.json>}
REPO_URL=https://github.com/jmorris0x0/bass-sentry.git
REPO_DIR=$HOME/bass-sentry

sudo apt-get update -y
sudo apt-get install -y git portaudio19-dev python3-venv python3-pip

if [ ! -d "$REPO_DIR" ]; then
  git clone "$REPO_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"
git pull --ff-only

if [ ! -f "remote-node/dag_files/$DAG" ]; then
  echo "DAG file remote-node/dag_files/$DAG not found" >&2
  exit 1
fi

./remote-node-setup.sh "$DAG"
