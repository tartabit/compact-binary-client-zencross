"""
Low Powered Tracker Demo for Murata 1SC EVK

This script demonstrates how to use the Murata 1SC EVK to create a low-powered
tracking device that sends telemetry data to the Tartabit IoT Bridge.

The script simulates sensor readings (temperature, battery, location) and sends
the data in a compact binary format to reduce bandwidth usage. It also handles
configuration commands from the server.

Packet types:
- 'T': Telemetry - sent periodically with sensor data and used on startup for identification
- 'C': Configuration - sent in response to a configuration request
- 'W': Write Configuration - received from server to update configuration

Author: Tartabit, LLC
Copyright: 2024 Tartabit, LLC
"""
import time
from threading import Thread, Event, Lock

import at
from config import get_config
import sensors

# Import decoders
from compact_binary_protocol import (
    PacketDecoder,
    DataReader,
)
# Import packets and data types
from compact_binary_protocol import (
    ConfigPacket,
    TelemetryPacket,
    PacketDecoder,
    DataReader,
    DataLocation,
    DataBasic,
    DataNull,
    DataMulti,
    DataSteps,
    DataVersions,
    DataNetworkInfo,
    DataCustomerId,
    DataKv,
)

port = get_config('port')
server_address = get_config('server')
reporting_interval = get_config('interval')
reading_interval = get_config('readings')
customer_id = get_config('code')
apn = get_config('apn')

# Initialize starting location from configuration (supports dotted and fallback to flat)
try:
    cfg_lat = get_config('location.lat')
    cfg_lon = get_config('location.lon')
    if cfg_lat is not None:
        sensors.last_lat = float(cfg_lat)
    if cfg_lon is not None:
        sensors.last_lon = float(cfg_lon)
except Exception as e:
    print(f"Warning: Invalid lat/lon in config: {e}")


term = at.AtTerminal(port, 115200)
if not term.open():
    print(f"Error opening serial port {port}. Please check the port and try again.")
    exit(0)
term.log = False

# Initialize transaction ID and acknowledgment tracking
transaction_id = 0
# Per-transaction ACK handling to support out-of-order ACKs
_ack_events = {}
_acked_txn_ids = set()
_ack_lock = Lock()
# Backward-compatible event if someone waits for "any" ack (not typical)
ack_event = Event()
def next_transaction_id():
    """
    Generate the next transaction ID, wrapping around at 65536.

    Returns:
        int: The next transaction ID.
    """
    global transaction_id
    transaction_id = (transaction_id + 1) % 65536
    return transaction_id

def send(reason, pkt):
    packet_bytes = pkt.to_bytes()
    term.send_command(f'AT%SOCKETDATA="SEND",1,{len(packet_bytes)},"{packet_bytes.hex()}"')
    pkt.print(reason)


def component_update(req, t_id):
    # Updates removed from protocol; no-op
    return

def wait_for_ack(txn_id=None, timeout=30):
    """
    Wait for an acknowledgment for the specified transaction ID.

    Supports out-of-order ACKs across multiple threads by using per-transaction
    events. If txn_id is None, this waits for any ACK (legacy behavior).
    """
    global _ack_events, _acked_txn_ids, _ack_lock, ack_event

    if txn_id is None:
        # Legacy: wait for any ack
        ack_event.clear()
        if ack_event.wait(timeout):
            return True
        print(f"Warning: Timeout waiting for any acknowledgment after {timeout} seconds")
        return False

    # Fast-path: if already acked
    with _ack_lock:
        if txn_id in _acked_txn_ids:
            return True
        ev = _ack_events.get(txn_id)
        if ev is None:
            ev = Event()
            _ack_events[txn_id] = ev

    # Wait for specific txn ack
    if ev.wait(timeout):
        # Clean-up mapping after successful wait
        with _ack_lock:
            _ack_events.pop(txn_id, None)
            _acked_txn_ids.add(txn_id)
        return True

    print(f"Warning: Timeout waiting for acknowledgment for txn {txn_id} after {timeout} seconds")
    return False


# Initialize modem and get device information
term.send_command('ATE0')  # Turn off command echo
term.send_command('ATE0')  # Turn off command echo

term.send_command('AT+CMEE=2')  # Enable verbose error reporting
if apn:
    print(f'Setting APN: {apn}')
    term.send_command(f'AT+CGDCONT=1,"IP","{apn}"')

# Get or set IMEI
imei_cfg = get_config('imei')
if imei_cfg:
    # Use the IMEI provided in command line arguments or config
    imei = imei_cfg
    print(f'IMEI: {imei} (from config)')
else:
    # Read IMEI from the modem
    rsp = term.send_command('AT+CGSN')
    imei = rsp.data if rsp.success else "unknown"
    print(f'IMEI: {imei}')

# Get ICCID
rsp = term.send_command('AT%CCID')
iccid = rsp.data if rsp.success else "unknown"
print(f'ICCID: {iccid}')

# Get network information
term.send_command('AT+COPS=0')
term.send_command('AT+COPS=3,2')
attached = False
network = '000000'
rat = 'unknown'
while not attached:
    rsp = term.send_command('AT+COPS?')
    if rsp.success:
        if len(rsp.split)==1:
            print("Waiting for network...")
            time.sleep(2)
        else:
            attached = True
            network = rsp.split[2] if rsp.success else "unknown"
            print(f'Network: {network}')
            if len(rsp.split)==4:
                rat_num = rsp.split[3]
                rat_map = {
                    '0': 'GSM',
                    '2': 'UTRAN',
                    '7': 'LTE-M',
                    '9': 'NB-IoT'
                }
                rat = rat_map.get(rat_num, f'unknown-{rat_num}')

                print(f'Radio Technology: {rat}')

# Set software version and get modem firmware version
software_version = '1.0.0'
rsp = term.send_command('AT+CGMR')
modem_version = rsp.data if rsp.success else "unknown"
print(f'Modem firmware version: {modem_version}')

term.send_command('AT%SOCKETCMD="DELETE",1')

print(f'Code: {customer_id}')
print(f'Server Address: {server_address}')

try:
    if server_address and ':' in server_address:
        server_host, server_port_str = server_address.split(':', 1)
        server_port = int(server_port_str)
    else:
        print('invalid server address, must be <host>:<port> format.')
        exit(0)
except Exception:
    print('invalid server address, must be <host>:<port> format.')
    exit(0)

term.send_command(f'AT%SOCKETCMD="ALLOCATE",1,"UDP","OPEN","{server_host}",{server_port},5000')
term.send_command('AT%SOCKETCMD="ACTIVATE",1')

def ack_handler_thread():
    """
    Thread function that handles Unsolicited Result Codes (URCs) from the modem.

    This function runs in a separate thread and waits for URCs from the modem.
    When a SOCKETEV URC is received, it reads the data from the socket and processes
    any commands received from the server.

    Supported commands:
    - 'C': Configuration request - responds with current configuration
    - 'W': Write configuration - updates server address and reporting interval
    """
    global server_address, reporting_interval, reading_interval
    try:
        while True:
            urc = term.wait_for_urc()
            if urc is not None:
                if urc.urc == 'SOCKETEV':
                    rsp = term.send_command('AT%SOCKETDATA="RECEIVE",1,1500')

                    print("*" * 50)
                    # Parse the response data to extract the 4th parameter
                    if rsp.success and rsp.data:
                        packet_hex = PacketDecoder.parse_response_data(rsp.data)
                        if packet_hex:
                            print(f"  Received packet: {packet_hex}")

                            # Decode the packet header (now includes timestamp)
                            decoded = PacketDecoder.decode_packet_header(packet_hex)
                            if decoded and len(decoded) >= 5:
                                version, command, txn_id, pkt_timestamp, data = decoded
                            else:
                                # Fallback for legacy (no timestamp parsed)
                                version, command, txn_id, data = decoded
                                pkt_timestamp = None
                            print(f"  Decoded header: version={version}, command={command}, txn_id={txn_id}, timestamp={pkt_timestamp}, data={data.hex()}")

                            # Handle different command types
                            if command and command[0] == 'A':
                                print(f"  Received '{command}' acknowledgement")
                                # Signal the specific transaction's event (out-of-order safe)
                                global _ack_events, _acked_txn_ids, _ack_lock, ack_event
                                with _ack_lock:
                                    _acked_txn_ids.add(txn_id)
                                    ev = _ack_events.pop(txn_id, None)
                                if ev is not None:
                                    ev.set()
                                # Also set the legacy any-ack event for compatibility
                                ack_event.set()
                            elif command and (command == 'CR' or (command[0] == 'C' and command[1] in ('R', '\0'))):
                                # Configuration request command (supports 'CR' and single-char 'C\0')
                                print(f"  Received '{command}' command, sending configuration (Telemetry/Kv)")
                                # Use the received transaction ID for the response
                                kv = DataKv({
                                    'server': server_address,
                                    'interval': str(reporting_interval),
                                    'readings': str(reading_interval),
                                })
                                tcfg = TelemetryPacket(imei, int(time.time()), txn_id, 'C', kv)
                                send('Requested Configuration (Telemetry/Kv)', tcfg)
                                # No need to wait for acknowledgment here as we're already in the URC handler
                            elif command and (command == 'CW' or (command[0] == 'W' and command[1] in ('\0', ' '))):
                                # Write configuration command (supports 'CW' and single-char 'W\0')
                                print(f"  Received '{command}' command, updating configuration")

                                # Decode configuration payload into ConfigPacket
                                try:
                                    decoded_cfg = ConfigPacket.decode(imei, txn_id, data)
                                    cfg = decoded_cfg.to_dict()
                                    server_address = cfg.get('server', server_address) or server_address
                                    try:
                                        reporting_interval = int(cfg.get('interval', reporting_interval))
                                    except Exception:
                                        pass
                                    try:
                                        reading_interval = int(cfg.get('readings', reading_interval))
                                    except Exception:
                                        pass
                                except Exception as e:
                                    print(f"  Failed to decode configuration payload: {e}")
                                    # Keep existing config, but acknowledge with current config
                                print(f"  Configuration updated: server={server_address}, reporting_interval={reporting_interval}, reading_interval={reading_interval}")

                                kv = DataKv({
                                    'server': server_address,
                                    'interval': str(reporting_interval),
                                    'readings': str(reading_interval),
                                })
                                tcfg = TelemetryPacket(imei, int(time.time()), txn_id, 'C', kv)
                                send('Configuration Updated (Telemetry/Kv)', tcfg)
                                # No need to wait for acknowledgment here as we're already in the URC handler
                            else:
                                print(f"Ignoring command '{command}', not supported (only 'C' and 'W' commands are supported)")
                    print("*" * 50)
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Exiting gracefully...")
        # Perform any necessary cleanup here
        term.stopping = True
        term.ser.close()
        print("Goodbye!")

ackHandler = Thread(target=ack_handler_thread, daemon=True)
ackHandler.start()

# Send startup telemetry
txn_id = next_transaction_id()
sensors_list = [
    DataCustomerId(customer_id),
    DataVersions(software_version, modem_version),
    DataNetworkInfo(network[0:3], network[3:6], rat),
]
startup_packet = TelemetryPacket(imei, int(time.time()), txn_id, 'P+', sensors_list)
send('Startup Telemetry', startup_packet)
wait_for_ack(txn_id)

# Send initial configuration via Telemetry (DataKv)
txn_id = next_transaction_id()
kv = DataKv({
                                    'server': server_address,
                                    'interval': str(reporting_interval),
                                    'readings': str(reading_interval),
                                })
config_packet = TelemetryPacket(imei, int(time.time()), txn_id, 'C', kv)
send('Initial Configuration (Telemetry/Kv)', config_packet)
wait_for_ack(txn_id)

def telemetry_thread():
    try:
        while True:
            txn_id = next_transaction_id()
            timestamp = int(time.time())
            battery = sensors.read_battery()
            rssi = sensors.read_rssi(term)

            # Build SensorMultiData records
            try:
                rc = max(1, int(reporting_interval // reading_interval))
            except Exception:
                rc = 1
            first_reading = timestamp - (rc * int(reading_interval))
            first_reading = first_reading - (first_reading % 60)
            records = []
            for _ in range(rc):
                records.append({
                    'temperature': sensors.read_temp(),
                    'humidity': sensors.read_hum(),
                })

            sensor_data = DataMulti(battery, rssi, first_reading, int(reading_interval), records)
            if get_config('location.type') == 'simulated':
                lat, lon = sensors.read_loc()
                loc = DataLocation.gnss(lat, lon)
            else:
                cell = sensors.read_serving_cell(term)
                loc = DataLocation.cell(cell['mcc'], cell['mnc'], cell['lac'], cell['cell_id'], cell['rssi'])

            # Publish location as a client-side value (no longer embedded in packets)
            try:
                print(f"Published Location: {loc.describe()}")
            except Exception:
                print("Published Location: (unavailable)")

            telemetry_packet = TelemetryPacket(imei, timestamp, txn_id, 'T', sensor_data)
            send('Telemetry', telemetry_packet)
            wait_for_ack(txn_id)

            print(f"Waiting for {reporting_interval} seconds before next transmission...")
            time.sleep(int(reporting_interval))
    except Exception as e:
        print(f"Telemetry thread encountered an error: {e}")


def motion_thread(motion_duration: int, motion_interval: int):
    try:
        while True:
            # Motion start
            txn_id = next_transaction_id()
            timestamp = int(time.time())
            battery = sensors.read_battery()
            rssi = sensors.read_rssi(term)
            if get_config('location.type') == 'simulated':
                lat, lon = sensors.read_loc()
                loc = DataLocation.gnss(lat, lon)
            else:
                cell = sensors.read_serving_cell(term)
                loc = DataLocation.cell(cell['mcc'], cell['mnc'], cell['lac'], cell['cell_id'], cell['rssi'])

            # Publish location at motion start
            try:
                print(f"Published Location: {loc.describe()}")
            except Exception:
                print("Published Location: (unavailable)")
            mstart = TelemetryPacket(imei, timestamp, txn_id, 'M+', loc)
            send('Motion Start', mstart)
            wait_for_ack(txn_id)

            # Duration of motion
            print(f"Motion active for {motion_duration} seconds...")
            time.sleep(int(motion_duration))

            # Motion stop
            txn_id = next_transaction_id()
            timestamp = int(time.time())
            battery = sensors.read_battery()
            rssi = sensors.read_rssi(term)
            steps = sensors.read_steps(int(motion_duration))
            if get_config('location.type') == 'simulated':
                lat, lon = sensors.read_loc()
                loc = DataLocation.gnss(lat, lon)
            else:
                cell = sensors.read_serving_cell(term)
                loc = DataLocation.cell(cell['mcc'], cell['mnc'], cell['lac'], cell['cell_id'], cell['rssi'])

            # Publish location at motion stop
            try:
                print(f"Published Location: {loc.describe()}")
            except Exception:
                print("Published Location: (unavailable)")
            mstop_data = [loc, DataSteps(battery=battery, rssi=rssi, steps=steps)]
            mstop = TelemetryPacket(imei, timestamp, txn_id, 'M-', mstop_data)
            send('Motion Stop', mstop)
            wait_for_ack(txn_id)

            # Wait for the interval before next motion cycle
            print(f"Waiting {motion_interval} seconds before next motion start...")
            time.sleep(int(motion_interval))
    except Exception as e:
        print(f"Motion thread encountered an error: {e}")


# Start worker threads
telemetry = Thread(target=telemetry_thread, daemon=True)
telemetry.start()

# Start motion thread only if both config values are provided
motion_duration = get_config('motionDuration')
motion_interval = get_config('motionInterval')
if motion_duration is not None and motion_interval is not None:
    try:
        md = int(motion_duration)
        mi = int(motion_interval)
        if md > 0 and mi > 0:
            motion = Thread(target=motion_thread, args=(md, mi), daemon=True)
            motion.start()
        else:
            print("motionDuration and motionInterval must be positive to enable motion events")
    except Exception as e:
        print(f"Invalid motion configuration: {e}")
else:
    print("Motion events disabled (motionDuration or motionInterval not set)")

# Block main thread waiting for Ctrl-C
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nCtrl+C detected. Exiting gracefully...")
    term.stopping = True
    term.ser.close()
    print("Goodbye!")
