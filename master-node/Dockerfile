FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the main application script
COPY master-node.py .
COPY data_handler.py .
COPY data_manager.py .

CMD ["python", "master-node.py"]
