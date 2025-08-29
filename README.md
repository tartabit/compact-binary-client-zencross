# Zencross Low-Powered UDP Client

This project provides a reference implementation of a UDP protocol that is efficient and simple to encode and decode for 
use with Murata cellular modules and the Tartabit IoT Bridge.

## Overview

The default configuration of the client represents a typical asset tracking / remote sensing scenario, 
and can be customized for your specific needs.  Note, this is a reference implementation and not a production-ready solution.

## Features

- Sends a "Power On" message when the device first starts
- Periodically sends telemetry data with location, temperature, humidity, battery level, and RSSI
- Responds to configuration requests from the server (C)
- Applies configuration updates from the server (W)
- Uses a compact binary protocol to minimize bandwidth usage

## Requirements

- Murata 1SC EVK
- Python 3.6 or higher
- Required Python packages (see requirements.txt)

## Installation

1. Clone this repository
2. Install the required Python packages:
   ```
   pip install -r requirements.txt
   ```

## Usage

Run the script with the following command:

```
python client.py [options]
```

## Configuring the client
The client can be configured using the config.yaml file located in the same directory as the script, or by providing 
command-line options.

### Command-line Options

- `-p, --port`: Serial port to connect to the modem (default: /dev/ttypUSB0). Examples: `/dev/ttyUSB0` (Linux), `COM3` (Windows).
- `-s, --server`: Server address in the format "hostname:port" (default: udp-eu.tartabit.com:10106)
- `-i, --interval`: Reporting interval in seconds (default: 120)
- `-r, --readings`: Reading interval in seconds (sensor sampling) (default: 60)
- `-m, --imei`: Override the IMEI (default: read from modem)
- `-c, --code`: Set customer code as an even-length hex string (e.g., `00000000`, `A1B2C3D4E6F8`). Encoded in P+ as a length-prefixed byte array (1-byte length + bytes).
- `-a, --apn`: Packet data APN (e.g., `connect.cxn`, `iot.1nce.net`)
- `--config`: Path to YAML config file (default: `config.yaml` in the same directory)

### Configuration via config.yaml

You can configure the demo using a YAML file placed next to the script (`config.yaml`) or by providing a custom path with `--config`.

- Precedence: command-line options override YAML values, which override built-in defaults.
- Dotted keys: nested YAML values (e.g., `location.lat`) are supported; for convenience, `lat`/`lon` at the top-level also work as a fallback.
- Available YAML fields: `port`, `server`, `location` (`type`, `lat`, `lon`), `interval`, `readings`, `motionDuration`, `motionInterval`, `imei`, `code`, `apn`.

Example `config.yaml`:
```
# Serial port for the modem (Windows example: COM3, Linux example: /dev/ttyUSB0)
port: COM9

# Server in the format host:port
server: udp-eu.tartabit.com:10106

location:
  # simulated, cellid
  type: simulated
  lat: 45.448803450183924
  lon: -75.63533774831912

# Reporting interval in seconds
interval: 120

# Reading interval in seconds (sensor sampling)
readings: 60

# Motion event settings (if either is missing, motion events are disabled)
motionDuration: 120   # seconds between motion start and motion stop
motionInterval: 600   # seconds from motion end to next motion start

# Optional: Override IMEI (otherwise read from modem)
imei: 

# Customer code (even-length hex string)
code: "00000000"

# Packet data APN, uncomment the APN for your SIM card or set your own.
# Telenor Connexion
apn: connect.cxn
# 1NCE
#apn: iot.1nce.net
```

Run with the YAML config:
```
python client.py --config config.yaml
```

Override values from the YAML on the command line:
```
python client.py --config config.yaml -s udp-eu.tartabit.com:10106 -i 120
```

### Examples

- Linux, default EU server and intervals:
  ```
  python client.py -p /dev/ttyUSB0
  ```

- Windows, specify COM port:
  ```
  python client.py -p COM3
  ```

- Override server and intervals:
  ```
  python client.py -s udp-us.tartabit.com:10106 -i 300 -r 60
  ```

- Override IMEI and set customer code:
  ```
  python client.py -m 123456789012345 -c 00000000
  ```

## Protocol and AT Commands

- UDP Protocol: See "Murata Low-Powered Tracker UDP Protocol Specification (v1)" in this repository for on-the-wire formats, state machine, and encoding details.
- AT Commands: See "AT Command Quickstart: Network Attach and UDP Transport (Murata 1SC EVK)" for the minimal set of commands to attach and send/receive UDP payloads. The Python demo mirrors this sequence.

Notes:
- IMEI is encoded on the wire as 8-byte packed BCD (e.g., "358419511056392" -> 03 58 41 95 11 05 63 92). See protocol.md for details.
- Defaults in this README match `client.py` (server udp-eu.tartabit.com:10106, report interval 120s, reading interval 60s).
- Motion events (M+/M-) are enabled when both `motionDuration` and `motionInterval` are present and positive in the YAML; otherwise motion is disabled.
- The demo acknowledges server A packets by matching Transaction IDs (ACKs may arrive out of order); configuration requests (C) are answered with a Configuration packet; write requests (W) are applied and confirmed.

## License

Copyright 2024 Tartabit, LLC. All rights reserved.
