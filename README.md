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
- `-m, --imei`: Override the IMEI (default: read from modem)
- `-c, --code`: Set customer code as an 8-hex-digit value (e.g., `00000000`)
- `--config`: Path to YAML config file (default: `config.yaml` in the same directory)

### Configuration via config.yaml

You can configure the demo using a YAML file placed next to the script (`config.yaml`) or by providing a custom path with `--config`.

- Precedence: command-line options override YAML values, which override built-in defaults.
- Available YAML fields: `port`, `server`, `interval`, `readings`, `imei`, `code`, `apn`.

Example `config.yaml`:
```
port: COM3
server: udp-us.tartabit.com:10106
interval: 300
readings: 60
imei:
code: "00000000"
apn: connect.cxn
```

Run with the YAML config:
```
python low_powered_tracker.py --config config.yaml
```

Override values from the YAML on the command line:
```
python low_powered_tracker.py --config config.yaml -s udp-eu.tartabit.com:10106 -i 120
```

### Examples

- Linux, default EU server and intervals:
  ```
  python low_powered_tracker.py -p /dev/ttyUSB0
  ```

- Windows, specify COM port:
  ```
  python low_powered_tracker.py -p COM3
  ```

- Override server and intervals:
  ```
  python low_powered_tracker.py -s udp-us.tartabit.com:10106 -i 300 -r 60
  ```

- Override IMEI and set customer code:
  ```
  python low_powered_tracker.py -m 123456789012345 -c 00000000
  ```

## Protocol and AT Commands

- UDP Protocol: See "Murata Low-Powered Tracker UDP Protocol Specification (v1)" in this repository for on-the-wire formats, state machine, and encoding details.
- AT Commands: See "AT Command Quickstart: Network Attach and UDP Transport (Murata 1SC EVK)" for the minimal set of commands to attach and send/receive UDP payloads. The Python demo mirrors this sequence.

Notes:
- Defaults in this README match `low_powered_tracker.py` (server udp-eu.tartabit.com:10106, report interval 120s, reading interval 60s).
- The demo acknowledges server A packets by matching Transaction IDs; configuration requests (C) are answered with a Configuration packet; write requests (W) are applied and confirmed.

## License

Copyright 2024 Tartabit, LLC. All rights reserved.
