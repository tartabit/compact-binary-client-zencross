"""
Configuration loader for Zencross UDP Client.

- Parses command-line arguments
- Loads optional YAML configuration file
- Exposes get_config(key) with precedence: CLI > YAML > DEFAULTS
- Supports dotted notation for nested YAML keys (e.g., "location.lat")

This module centralizes all configuration handling for client.py and related scripts.
"""
from __future__ import annotations
import os
import argparse
from typing import Any, Dict, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

# Defaults aligned with current zencross-udp-client usage
DEFAULTS: Dict[str, Any] = {
    'port': '/dev/ttypUSB0',
    'server': 'udp-eu.tartabit.com:10106',
    'interval': 120,
    'readings': 60,
    'imei': None,
    'code': '00000000',
    'apn': None,
}

# Parse CLI arguments once on module import
_parser = argparse.ArgumentParser(
    prog='Zencross UDP Client',
    description='Low-powered protocol demonstration sending data to the Tartabit IoT Bridge using a compact binary protocol',
    epilog='Copyright 2025 Tartabit, LLC.')
_parser.add_argument('-p', '--port', help='Serial port to connect to the modem', default=None)
_parser.add_argument('-s', '--server', help='Server address in the format "hostname:port"', default=None)
_parser.add_argument('-i', '--interval', help='Reporting interval in seconds', type=int, default=None)
_parser.add_argument('-r', '--readings', help='Reading interval in seconds', type=int, default=None)
_parser.add_argument('-m', '--imei', help='Override the IMEI (default: read from modem)', default=None)
_parser.add_argument('-c', '--code', help='Set customer code (default: 00000000)', default=None)
_parser.add_argument('-a', '--apn', help='Packet data APN', default=None)
_parser.add_argument('--config', help='Path to YAML config file', default=None)

# Note: parse_known_args allows other modules to add their own args if needed
_args, _unknown = _parser.parse_known_args()

# Load YAML configuration (optional)
_config: Dict[str, Any] = {}
_config_path = _args.config or os.path.join(os.path.dirname(__file__), 'config.yaml')
if _config_path and os.path.exists(_config_path) and yaml is not None:
    try:
        with open(_config_path, 'r') as f:
            loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                _config = loaded
    except Exception as e:
        print(f"Warning: Failed to load config file {_config_path}: {e}")


def _get_from_dict_path(d: Dict[str, Any], dotted: str) -> Optional[Any]:
    """Get a value from a dict via dotted notation, safely.

    Returns None if any segment does not exist.
    """
    cur: Any = d
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def get_config(key: str, default: Any = None) -> Any:
    """Return configuration value using precedence: CLI > YAML > DEFAULTS.

    - Supports dotted notation to access nested YAML keys, e.g. "location.lat".
    - For convenience and backward compatibility:
      * If key is "location.lat" or "location.lon" and the nested value is
        missing, this function will also look for top-level "lat"/"lon".
    """
    # 1) CLI override for simple (non-dotted) keys based on argparse destinations
    if '.' not in key:
        cli_val = getattr(_args, key, None)
        if cli_val is not None:
            return cli_val
    # No CLI override for dotted keys (we do not expose nested CLI args)

    # 2) YAML via dotted path
    yaml_val: Any = None
    if isinstance(_config, dict):
        if '.' in key:
            yaml_val = _get_from_dict_path(_config, key)
            # Back-compat fallback for location.lat/lon to flat lat/lon
            if yaml_val is None and key in ('location.lat', 'location.lon'):
                flat_key = 'lat' if key.endswith('.lat') else 'lon'
                yaml_val = _config.get(flat_key)
        else:
            yaml_val = _config.get(key)

    if yaml_val is not None:
        return yaml_val

    # 3) Defaults for simple keys only
    if '.' not in key and key in DEFAULTS:
        return DEFAULTS[key]

    # 4) Fallback to provided default
    return default


__all__ = ['get_config', 'DEFAULTS']
