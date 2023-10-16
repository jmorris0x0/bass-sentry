FROM python:3.9-slim

# Install Avahi and dependencies
RUN apt-get update && apt-get install -y avahi-daemon avahi-utils libavahi-compat-libdnssd-dev && apt-get clean

# Set up Avahi
COPY mymasterservice.service /etc/avahi/services/

# Set the working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the main application script
COPY master_node.py .

CMD ["python", "master_node.py"]
