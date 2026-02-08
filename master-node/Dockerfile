FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Install Python dependencies
COPY master-node/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the main application scripts
COPY master-node/master-node.py .
COPY master-node/correlation.py .
COPY master-node/node_manager.py .
COPY master-node/correlation_strategies.py .
COPY master-node/adaptive_correlation.py .

# Copy common directory for pluggable transports
COPY common ./common

CMD ["python", "master-node.py"]
