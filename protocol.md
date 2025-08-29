# Zencross Low-Powered UDP Protocol Specification

This document specifies a binary UDP protocol that is flexible, efficient, and can be easily implemented in the Zencross ecosystem.  It defines on-the-wire message formats, field encodings, command semantics, and the expected state/flow so the protocol can be implemented in any programming language and transported over any UDP stack.

All multi-byte numeric fields are big-endian. All strings are ASCII unless stated otherwise.

## Transport Layer
- Protocol: UDP
- Port/Endpoint: Device connects to a configured UDP server (e.g., udp-us.tartabit.com:10106). The server address is also carried in configuration messages.
- Reliability: Application-level acknowledgments (Ack, command "A") are used per message, keyed by Transaction ID.
- Framing: Each UDP datagram carries exactly one application packet defined in this document.

This protocol is independent of the specific modem AT commands used in the sample application. Only the UDP payload format is specified here.

## Common Packet Header
Every packet starts with a fixed header:
- Version: 1 byte
    - Current value: 1
- Command: 2 bytes
    - Two ASCII characters. If the logical command is a single character, the second byte is a null ("\0"). Examples: "T\0", "C\0", "P+", "A\0".
- Transaction ID: 2 bytes (uint16, big-endian)
    - Sequence number for matching requests and acknowledgments. Wraps modulo 65536.
- IMEI: 8 bytes (packed BCD)
    - Encoding: decimal digits packed two per byte, low nibble = first digit, high nibble = second digit. If the number of digits is odd (e.g., 15), prepend a leading 0 nibble to make an even number of nibbles (example below).
    - Example: "358419511056392" -> 03 58 41 95 11 05 63 92.

Header total: 1 + 2 + 2 + 8 = 13 bytes.

Following the header is the Command-specific body (which may be empty).

## Commands Overview
The protocol is centered around commands, each packet has a command field that describes the intent for each message.
- Device to Cloud commands
    - P+ (Power On): Device → Server
    - C (Configuration): Device → Server (in response to request, or proactively on startup)
    - T (Telemetry): Device → Server (periodic)
    - M+ (Motion Start): Device → Server (event)
    - M- (Motion Stop): Device → Server (event)
- Cloud to device commands
    - A (Acknowledge): Server → Device (for any packet that requires ack)
    - C (Configuration Request): Server → Device (request device to send its current configuration)
    - W (Write Configuration): Server → Device (update device configuration)

When you implement the protocol, you can add other commands as needed and implement on the IoT Bridge to facilitate parsing and handling.  It is recommended to maintain the format of these standard commands.

### Packet: Power On (Command "P+")
Send when the device powers on and connects to the network.

Body, in order:
- Customer ID: VarBytes
    - Encoding: 1-byte length N (uint8) followed by N raw bytes.
    - The bytes are obtained by hex-decoding the provided code string (even-length hex characters). Example: code "00000000" -> length=4, bytes 00 00 00 00.
- Software Version: VarString
- Modem Firmware Version: VarString
- MCC: VarString
- MNC: VarString
- RAT: VarString (e.g., "LTE-M", "NB-IoT")

Semantics:
- Sent once at application startup to announce identity and environment.
- Must be acknowledged (A) by the server with the same Transaction ID.

### Packet: Configuration (Command "C")
Send after the `Power On` command or if the server requests the configuration to be sent.

Body, in order:
- Server Address: VarString
    - Format: "hostname:port" (e.g., "udp-eu.tartabit.com:10106").
- Publish Interval: 4 bytes (uint32)
    - Seconds between telemetry publishes.
- Reading Interval: 4 bytes (uint32)
    - Seconds between individual sensor readings collected into a telemetry bundle.

Semantics:
- Sent initially after Power On.
- Also sent in response to a server Configuration Request (C) or after applying a Write Configuration (W).
- Must be acknowledged (A) by the server.

### Packet: Telemetry (Command "T")
The default way to send time-series event data.  This packet type can accomodate different sensor configurations through the SensorData structure.

Body, in order:
- Timestamp: 4 bytes (uint32)
    - Unix time (seconds since epoch).
- LocationData: variable, see below
- SensorDataCount: 1 byte (uint8)
    - Number of SensorData structures that follow; currently 1 in the reference app.
- SensorData: variable, see below (the sample uses SensorMultiData v1)

Semantics:
- Sent periodically based on the configured Publish Interval.
- Must be acknowledged (A) by the server.

### Packet: Acknowledge (Command "A")

Direction: Server → Device

Body:
- None (empty)

Semantics:
- Acknowledges receipt and acceptance of a packet that requires acknowledgment.
- The Transaction ID in the header must match the Transaction ID of the packet being acknowledged.

Device behavior:
- For each sent packet that expects an ack (P+, C, T, M+, M-), the device waits up to a timeout (default 30 seconds in the sample) for an A with the same Transaction ID. If not received, it treats it as a timeout.
- ACKs may arrive out of order relative to packet sends; devices must match ACKs strictly by Transaction ID (not by sequence of arrival).

### Packet: Configuration Request (Command "C") — Server → Device

Direction: Server → Device

Body:
- None (empty)

Semantics:
- Instructs the device to send a Configuration (C) packet in reply.
- The device reuses the Transaction ID from the request in the response.

### Packet: Write Configuration (Command "W") — Server → Device

Direction: Server → Device

Body, in order:
- New Server Address: VarString ("hostname:port")
- New Publish Interval: 4 bytes (uint32)
- New Reading Interval: 4 bytes (uint32)

Semantics:
- Instructs the device to update its runtime configuration. Upon applying the changes, the device responds with a Configuration (C) packet echoing the new values and using the same Transaction ID as the W packet.

## Data encodings
Below are the specific encodings for the different special data types.

### Variable-Length String Encoding
Some bodies use variable-length ASCII strings, they are encoded as:
- Length: 1 byte (uint8) = number of bytes in string (max 255)
- Data: “Length” bytes of ASCII characters

Note: If a string exceeds 255 bytes, it must be truncated to 255.

### LocationData Encoding

LocationData is a type-tagged structure embedded within Telemetry packets.

- Type: 1 byte (uint8)
    - 1 = GNSS
    - 2 = CELL
    - 3 = WIFI

When Type = 1 (GNSS):
- Latitude: 4 bytes (float32, IEEE-754, big-endian)
- Longitude: 4 bytes (float32, IEEE-754, big-endian)

When Type = 2 (CELL):
- MCC: VarString
- MNC: VarString
- LAC: VarString
- Cell ID: VarString
- RSSI: 1 byte (uint8)

When Type = 3 (WIFI):
- Count: 1 byte (uint8)
- repeats for `count` SSIDs
    - SSID: VarString
    - RSSI: 1 byte (int8)

### SensorData Encoding

The Telemetry and Motion packets carry one or more SensorData items. Each item begins with a generic header that allows for versioning and variable-length payloads.

Common SensorData header:
- sensor_type: 1 byte (uint8)
- sensor_version: 1 byte (uint8)
- sensor_length: 1 byte (uint8) — number of bytes in the payload that follows

#### SensorMultiData (type=2, version=1)
Payload:
- battery: 1 byte (uint8) — percentage
- rssi: 1 byte (uint8)
- first_record_time: 4 bytes (uint32) — Unix time of the first sample in the series
- record_interval: 2 bytes (uint16) — seconds between samples
- record_count: 1 byte (uint8)
- records: record_count repetitions of:
    - temperature: 2 bytes (int16) — tenths of degrees Celsius (value = temperature_C × 10)
    - humidity: 2 bytes (int16) — tenths of percent RH (value = humidity_% × 10)

#### NullSensorData (type=0, version=0)
Payload: (empty)
- Used in Motion Start (M+) to indicate no sensor values are attached.

#### MotionSensorData (type=3, version=1)
Payload:
- battery: 1 byte (uint8) — percentage
- rssi: 1 byte (uint8)
- steps: 4 bytes (int32)

#### <Custom Encoding>
Below are the steps to define your own encoding.
1. Assign a type code and start at version 1.
2. Record format is controlled by you, specify anything you want.
3. If you change the structure, update the version.

Notes:
- You can extend the Telemetry packet with additional data formats by defining your own type/version that has dynamic collections of data fields available.

### Packet: Motion Start (Command "M+")
Send to indicate the start of a motion window.

Body, in order:
- Timestamp: 4 bytes (uint32)
    - Unix time (seconds since epoch).
- LocationData: variable, see below
- SensorDataCount: 1 byte (uint8)
    - Number of SensorData structures that follow; currently 1.
- SensorData: NullSensorData (type=0, version=0, length=0)

Semantics:
- Used to mark the beginning of a motion activity period. Must be acknowledged (A).

### Packet: Motion Stop (Command "M-")
Send to indicate the end of a motion window.

Body, in order:
- Timestamp: 4 bytes (uint32)
    - Unix time (seconds since epoch).
- LocationData: variable, see below
- SensorDataCount: 1 byte (uint8)
    - Number of SensorData structures that follow; currently 1.
- SensorData: MotionSensorData (type=3, version=1)
    - Payload: battery (u8), rssi (u8), steps (i32)

Semantics:
- Used to mark the end of a motion activity period and report summary stats.
- Must be acknowledged (A).

## State and Flow

On startup:
1. Initialize and connect to network; create/activate UDP socket to the configured server.
2. Send Power On (P+) with a new Transaction ID; wait for Acknowledgment (A) with matching Transaction ID.
3. Send Configuration (C) with current server address and intervals; wait for Acknowledgment (A).

Operational loop:
1. At each Publish Interval:
    - Gather readings: compute a series of temperature/humidity pairs based on Reading Interval; capture battery and RSSI.
    - Get location (GNSS or CELL).
    - Send Telemetry (T) with new Transaction ID.
    - Wait for Acknowledgment (A). On timeout, device may log a warning and continue (sample behavior), or you may implement retries/backoff.

Server-initiated commands (asynchronously, any time):
- Configuration Request (C): Device responds by sending Configuration (C) using the same Transaction ID as the request.
- Write Configuration (W): Device reads New Server Address, Publish Interval, Reading Interval; applies them; then sends Configuration (C) with the same Transaction ID echoing the new values.

Transaction ID handling:
- Device increments an internal 16-bit counter modulo 65536 for each outbound packet that expects an Ack. For responses to server commands, it uses the request’s Transaction ID in the response.

Acknowledgment handling:
- Device considers a packet acknowledged only when it receives an A with a matching Transaction ID. An A with a different Transaction ID should not be considered a valid ack for the current in-flight packet.
- ACKs may arrive out of order relative to the order of sent packets; implementations must match and resolve ACKs by Transaction ID.

### Binary Layout Summaries

Header (13 bytes):
- [0] Version (u8)
- [1..2] Command (2×ASCII)
- [3..4] Transaction ID (u16 be)
- [5..12] IMEI (8×packed BCD)

P+ body:
- VarBytes: Customer ID (1-byte length N, then N bytes)
- VarString: Software Version
- VarString: Modem Version
- VarString: MCC
- VarString: MNC
- VarString: RAT

C body (Device → Server):
- VarString: Server Address
- [..+4] Publish Interval (u32 be)
- [..+4] Reading Interval (u32 be)

T body:
- [..+4] Timestamp (u32 be)
- LocationData (per type)
- [..+1] SensorDataCount (u8) — number of SensorData items (currently 1)
- SensorData item(s) (per type/version)

A body:
- empty

C body (Server → Device):
- empty

M+ body:
- [..+4] Timestamp (u32 be)
- LocationData (per type)
- [..+1] SensorDataCount (u8) — number of SensorData items (1)
- SensorData: NullSensorData (type=0, ver=0, len=0)

M- body:
- [..+4] Timestamp (u32 be)
- LocationData (per type)
- [..+1] SensorDataCount (u8) — number of SensorData items (1)
- SensorData: MotionSensorData (type=3, ver=1, len=payload)
    - payload: battery (u8), rssi (u8), steps (i32)

W body (Server → Device):
- VarString: New Server Address
- [..+4] New Publish Interval (u32 be)
- [..+4] New Reading Interval (u32 be)

### Encoding Notes and Edge Cases

- Endianness: All multi-byte integers and float32 are big-endian.
- Floats: GNSS latitude/longitude are IEEE-754 float32 (binary32) big-endian.
- Strings: ASCII only; not null-terminated; prefixed with length byte when VarString is used.
- IMEI: Encoded as 8-byte packed BCD in the header.
- Command 2-byte field: For single-char commands, second byte is 0x00. For “P+”, it is ASCII 'P' and '+'.
- Timeouts and retries: The sample waits 30 seconds for Ack; implementers may choose retry strategies.
- Record counts: Ensure record_count × record_size does not exceed your maximum packet size for your transport. UDP MTU considerations apply.

### Minimal Pseudocode for Packing/Unpacking

Header pack:
- write_u8(1)
- write_u8(cmd[0])
- write_u8(cmd[1] or 0)
- write_u16_be(txn_id)
- write_bytes(imei_ascii_15)

VarString pack:
- write_u8(len(ascii_bytes))
- write_bytes(ascii_bytes)

Ack (A) packet from server:
- header with command="A\0", matching txn_id, same IMEI as target device; no body.

### Interoperability Checklist

- Use big-endian consistently.
- Keep IMEI exactly 15 ASCII bytes.
- Match Transaction ID in Acks and in responses to server-initiated commands.
- Respect VarString length limits (≤255).
- For Telemetry, ensure LocationData and SensorData follow the specified type/version contracts.
- Validate and bound record_count to fit within typical UDP MTUs (e.g., < 1200 bytes payload for safety).

### Example Field Values

- Version: 0x01
- Commands: "P+" (0x50 0x2B), "T\0" (0x54 0x00), "C\0" (0x43 0x00), "W\0" (0x57 0x00), "A\0" (0x41 0x00)
- Transaction ID: 0..65535 (wraps)
- GNSS floats: 4-byte IEEE-754 big-endian
- SensorMulti units: temperature ×10 (int16), humidity ×10 (int16)

### Conformance

An implementation conforms to this protocol if it:
- Emits packets with the header layout and body encodings defined above.
- Processes incoming packets by header, command, and body as described.
- Implements the acknowledgment model using Transaction IDs.
- Supports at least P+, C (device→server), T, A, C (server→device), and W (server→device).
