"""
HTTP Transport Implementation

Uses HTTP POST/GET for communication over cellular/internet.
Perfect for:
- Remote monitoring (neighbor's house, 5G hotspot)
- Cellular connectivity (unlimited range)
- Simple cloud deployments
- Backup transport when WiFi/LoRa unavailable

No additional hardware required (uses built-in networking).
Bandwidth: 1-100 Mb/s (more than enough for 16 kb/s per node)
Range: Unlimited (wherever you have internet)
"""

import json
import logging
import threading
import time
from typing import Callable, Dict, Any, Optional
from urllib.parse import urljoin

import requests

from common.transport import Transport

logger = logging.getLogger(__name__)


class HTTPTransport(Transport):
    """HTTP transport implementation for internet/cellular communication."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize HTTP transport.

        Config options:
            base_url: Server base URL (e.g., 'http://192.168.1.100:8080')
            node_id: This node's ID (required)
            poll_interval: Polling interval in seconds (default: 0.5)
            timeout: Request timeout in seconds (default: 5)
            auth_token: Optional authentication token
        """
        super().__init__(config)

        self.base_url = config.get("base_url", "http://localhost:8080")
        self.node_id = config.get("node_id")
        if not self.node_id:
            raise ValueError("HTTP transport requires 'node_id' in config")

        self.poll_interval = config.get("poll_interval", 0.5)
        self.timeout = config.get("timeout", 5)
        self.auth_token = config.get("auth_token")

        # Session for connection pooling
        self.session = requests.Session()
        if self.auth_token:
            self.session.headers.update({"Authorization": f"Bearer {self.auth_token}"})

        # Polling thread
        self.poll_thread = None
        self.running = False

        # Statistics
        self.stats = {
            "messages_sent": 0,
            "messages_received": 0,
            "messages_failed": 0,
            "http_errors": 0,
        }

    def connect(self) -> bool:
        """Connect to HTTP server."""
        try:
            logger.info(f"Connecting to HTTP server at {self.base_url}")

            # Test connection
            response = self.session.get(
                urljoin(self.base_url, "/health"), timeout=self.timeout
            )
            response.raise_for_status()

            self.connected = True
            logger.info("HTTP transport connected")

            # Start polling thread
            self.running = True
            self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self.poll_thread.start()

            return True

        except requests.RequestException as e:
            logger.error(f"HTTP connection failed: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from HTTP server."""
        logger.info("Disconnecting HTTP transport")
        self.running = False
        if self.poll_thread:
            self.poll_thread.join(timeout=2)
        self.session.close()
        self.connected = False

    def send(self, topic: str, data: Dict[str, Any], **kwargs) -> bool:
        """
        Send data via HTTP POST.

        Args:
            topic: Topic string (will be sent in request)
            data: Data to send (JSON-serialized)
            **kwargs: Optional request parameters

        Returns:
            bool: True if sent successfully
        """
        if not self.connected:
            logger.warning("HTTP not connected, cannot send")
            self.stats["messages_failed"] += 1
            return False

        try:
            # Build request payload
            payload = {
                "node_id": self.node_id,
                "topic": topic,
                "data": data,
                "timestamp": time.time(),
            }

            # Send POST request
            response = self.session.post(
                urljoin(self.base_url, "/publish"), json=payload, timeout=self.timeout
            )
            response.raise_for_status()

            self.stats["messages_sent"] += 1
            logger.debug(f"HTTP sent to topic {topic}")
            return True

        except requests.RequestException as e:
            logger.error(f"HTTP send error: {e}")
            self.stats["messages_failed"] += 1
            self.stats["http_errors"] += 1
            return False

    def subscribe(self, topic: str, callback: Callable[[str, Dict], None]):
        """
        Subscribe to topic pattern.

        Note: HTTP uses polling, so subscriptions are stored and
        checked during polling.

        Args:
            topic: Topic pattern (supports wildcards: + for single level, # for multi-level)
            callback: Function called with (topic, data) when message arrives
        """
        logger.info(f"Registering HTTP callback for topic: {topic}")
        self.callbacks[topic] = callback

    def _poll_loop(self):
        """Background thread to poll for messages."""
        logger.info("HTTP polling loop started")

        while self.running:
            try:
                # Poll for messages
                self._poll_messages()
                time.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"HTTP polling error: {e}")
                time.sleep(1)

        logger.info("HTTP polling loop stopped")

    def _poll_messages(self):
        """Poll server for new messages."""
        try:
            # Get topics we're subscribed to
            topics = list(self.callbacks.keys())
            if not topics:
                return

            # Request messages for subscribed topics
            response = self.session.post(
                urljoin(self.base_url, "/poll"),
                json={"node_id": self.node_id, "topics": topics},
                timeout=self.timeout,
            )
            response.raise_for_status()

            # Process received messages
            messages = response.json().get("messages", [])
            for msg in messages:
                topic = msg.get("topic")
                data = msg.get("data")

                if topic and data:
                    # Call matching callbacks
                    for topic_pattern, callback in self.callbacks.items():
                        if self._topic_matches(topic_pattern, topic):
                            callback(topic, data)

                    self.stats["messages_received"] += 1

        except requests.RequestException as e:
            logger.debug(f"HTTP poll error: {e}")
            self.stats["http_errors"] += 1

    def _topic_matches(self, pattern: str, topic: str) -> bool:
        """
        Check if topic matches pattern (with wildcards).

        Supports:
        - + : Single level wildcard
        - # : Multi-level wildcard

        Args:
            pattern: Pattern with wildcards
            topic: Actual topic

        Returns:
            bool: True if matches
        """
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")

        i = 0
        j = 0

        while i < len(pattern_parts) and j < len(topic_parts):
            if pattern_parts[i] == "#":
                return True  # Multi-level wildcard matches rest
            elif pattern_parts[i] == "+":
                # Single level wildcard
                i += 1
                j += 1
            elif pattern_parts[i] == topic_parts[j]:
                i += 1
                j += 1
            else:
                return False

        return i == len(pattern_parts) and j == len(topic_parts)

    def get_stats(self) -> Dict[str, Any]:
        """Get transport statistics."""
        return {
            **self.stats,
            "connected": self.connected,
            "poll_interval": self.poll_interval,
        }


# Example HTTP server implementation (for reference)
"""
Simple HTTP server for Bass Sentry (Flask example):

from flask import Flask, request, jsonify
from collections import defaultdict
import threading
import time

app = Flask(__name__)

# Message queues per node
message_queues = defaultdict(list)
queue_lock = threading.Lock()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/publish', methods=['POST'])
def publish():
    data = request.json
    topic = data.get('topic')
    message_data = data.get('data')

    # Broadcast to all nodes subscribed to this topic
    with queue_lock:
        for node_id in message_queues.keys():
            message_queues[node_id].append({
                'topic': topic,
                'data': message_data,
                'timestamp': time.time()
            })

    return jsonify({'status': 'ok'})

@app.route('/poll', methods=['POST'])
def poll():
    data = request.json
    node_id = data.get('node_id')
    topics = data.get('topics', [])

    # Get messages for this node
    with queue_lock:
        messages = message_queues.get(node_id, [])

        # Filter by subscribed topics
        filtered = [
            msg for msg in messages
            if any(topic_matches(pattern, msg['topic']) for pattern in topics)
        ]

        # Clear delivered messages
        message_queues[node_id] = []

    return jsonify({'messages': filtered})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
"""
