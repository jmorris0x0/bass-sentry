FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY web/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy web application
COPY web/ ./web/
COPY master-node/correlation.py ./master_node/
RUN touch ./master_node/__init__.py

# Set working directory for Flask
WORKDIR /app/web

ENV FLASK_APP=server.py
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python", "server.py"]
