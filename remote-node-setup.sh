#!/bin/bash

# Check if dag file is passed as an argument
if [ -z "$1" ]; then
  echo "Usage: ./install.sh <dag_file>"
  exit 1
fi

DAG_FILE=$1
SERVICE_NAME="bass_sentry_remote_node"
REPO_DIR=$(pwd)
PYTHON_EXEC="$REPO_DIR/.venv/bin/python3"

# Update the package list
sudo apt-get update -y

# Install necessary system packages
sudo apt-get install -y python3-venv python3-pip portaudio19-dev git

# Create Python virtual environment if it doesn't exist
if [ ! -d "$REPO_DIR/.venv" ]; then
  python3 -m venv "$REPO_DIR/.venv"
  echo "Virtual environment created at $REPO_DIR/.venv"
fi

# Activate the virtual environment
source "$REPO_DIR/.venv/bin/activate"

# Install Python packages
pip install -r "$REPO_DIR/remote-node/requirements.txt"

# Create a systemd service file for the Python program
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOL
[Unit]
Description=Bass Sentry Remote Node Service
After=network.target

[Service]
ExecStart=$PYTHON_EXEC $REPO_DIR/remote-node/remote_node.py $REPO_DIR/remote-node/dag_files/$DAG_FILE
WorkingDirectory=$REPO_DIR/remote-node
StandardOutput=inherit
StandardError=inherit
Restart=always
User=$USER

[Install]
WantedBy=multi-user.target
EOL

# Enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME.service"
sudo systemctl start "$SERVICE_NAME.service"

# Verify service status
echo "Installation complete. Checking service status..."
sudo systemctl status "$SERVICE_NAME.service" --no-pager

