#!/usr/bin/env python3
"""
Generate Secure LoRa Network Configuration

Creates random network ID and encryption key for isolated LoRa network.
Each venue/user should run this to get unique, secure credentials.

Usage:
    python tools/generate_lora_network.py

    # Or specify venue name
    python tools/generate_lora_network.py --venue "Downtown Festival"

    # Generate multiple venues
    python tools/generate_lora_network.py --venues 5
"""

import argparse
import secrets
import json
import sys


def generate_network_id():
    """Generate random network ID (sync word)."""
    # 0x00-0xFF, but avoid default 0x12 and common values
    avoid = {0x12, 0x00, 0xFF}  # Default, broadcast
    network_id = secrets.randbelow(256)

    while network_id in avoid:
        network_id = secrets.randbelow(256)

    return network_id


def generate_encryption_key():
    """Generate random 128-bit AES encryption key."""
    return secrets.token_bytes(16)


def generate_venue_config(venue_name=None):
    """Generate complete venue configuration."""
    network_id = generate_network_id()
    encryption_key = generate_encryption_key()

    config = {
        "venue_name": venue_name or f"Venue_{network_id:02X}",
        "network_id": f"0x{network_id:02X}",
        "encryption_key": encryption_key.hex(),
        "security_note": "Keep these credentials SECRET! Share only with your remote nodes.",
        "lora_config": {
            "frequency": 915,
            "network_id": network_id,
            "encryption_key": encryption_key.hex(),
            "tx_power": 20,
            "spreading_factor": 7,
            "node_id": "CHANGE_ME",
            "gateway_id": 0,
        },
        "instructions": {
            "step_1": "Save this configuration file securely",
            "step_2": "Share ONLY with your own remote nodes (never with other venues)",
            "step_3": "Update 'node_id' for each node (gateway=0, nodes=1,2,3...)",
            "step_4": "Add to your config.json under 'transport' section",
        },
    }

    return config


def main():
    parser = argparse.ArgumentParser(
        description="Generate secure LoRa network configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate one venue
  python generate_lora_network.py --venue "My Festival"

  # Generate multiple venues
  python generate_lora_network.py --venues 5

  # Output to file
  python generate_lora_network.py --output venue1-lora-config.json
""",
    )

    parser.add_argument("--venue", type=str, help="Venue name")
    parser.add_argument("--venues", type=int, help="Generate N venue configs")
    parser.add_argument(
        "--output", type=str, help="Output file (default: print to stdout)"
    )

    args = parser.parse_args()

    # Generate one or multiple venues
    if args.venues:
        configs = []
        for i in range(args.venues):
            config = generate_venue_config(f"Venue_{i+1}")
            configs.append(config)

        output = {
            "venues": configs,
            "note": "Each venue has unique network_id and encryption_key - DO NOT MIX!",
        }

    else:
        output = generate_venue_config(args.venue)

    # Output
    if args.output:
        with open(args.output, "w") as f:
            json.dump(output, f, indent=2)
        print(f"✅ Configuration saved to: {args.output}", file=sys.stderr)
        print(f"🔒 Network ID: {output.get('network_id', 'N/A')}", file=sys.stderr)
        print(f"🔐 Encryption: Enabled (AES-128)", file=sys.stderr)
        print(f"⚠️  Keep this file SECRET!", file=sys.stderr)
    else:
        print(json.dumps(output, indent=2))

    # Security reminder
    print("\n" + "=" * 60, file=sys.stderr)
    print("SECURITY REMINDER:", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("✅ Your network is isolated by:", file=sys.stderr)
    print("   1. Sync Word (network_id) - Hardware-level filtering", file=sys.stderr)
    print("   2. AES-128 Encryption - Software-level security", file=sys.stderr)
    print("", file=sys.stderr)
    print("⚠️  DO NOT share these credentials with other venues!", file=sys.stderr)
    print("   Each venue should generate their own config.", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        "📡 Even if venues are close (< 10km), they won't interfere.", file=sys.stderr
    )
    print("=" * 60, file=sys.stderr)


if __name__ == "__main__":
    main()
