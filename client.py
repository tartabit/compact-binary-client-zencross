"""
Low Powered Tracker Demo for Murata 1SC EVK

This script demonstrates how to use the Murata 1SC EVK to create a low-powered
tracking device that sends telemetry data to the Tartabit IoT Bridge.

The script simulates sensor readings (temperature, battery, location) and sends
the data in a compact binary format to reduce bandwidth usage. It also handles
configuration commands from the server.

Packet types:
- 'P+': Power On - sent when the device first starts up
- 'T': Telemetry - sent periodically with sensor data
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
# Import packets
from compact_binary_protocol import (
    PowerOnPacket,
    ConfigPacket,
    TelemetryPacket,
    MotionStartPacket,
    MotionStopPacket,
    UpdateRequestPacket,
    UpdateStatusPacket,
    PacketDecoder,
    DataReader,
)
# Import sensor data types
from compact_binary_protocol import (
    LocationData,
    SensorDataBasic,
    SensorDataNull,
    SensorDataMulti,
    SensorDataSteps,
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
    try:
        # 1) Send started status
        started_pkt = UpdateStatusPacket(imei, t_id, req.component, 'started', '')
        send('Update Started', started_pkt)
        # 2) Wait for configured duration
        try:
            duration = int(get_config('updateDuration', 5))
        except Exception:
            duration = 5
        time.sleep(max(0, duration))
        # 3) Determine success/failure using configured failure rate
        try:
            failure_rate = float(get_config('updateFailureRate', 0.0))
        except Exception:
            failure_rate = 0.0
        if failure_rate < 0:
            failure_rate = 0.0
        if failure_rate > 1:
            failure_rate = 1.0
        import random
        failed = random.random() < failure_rate
        # 4) Send final status
        if failed:
            final = UpdateStatusPacket(imei, t_id, req.component, 'failed', 'Simulated failure')
            send('Update Failed', final)
        else:
            final = UpdateStatusPacket(imei, t_id, req.component, 'success', '')
            send('Update Success', final)
    except Exception as ex:
        try:
            err = UpdateStatusPacket(imei, t_id, req.component, 'failed', f'Exception: {ex}')
            send('Update Failed (exception)', err)
        except Exception:
            pass

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

                            # Decode the packet header
                            version, command, txn_id, data = PacketDecoder.decode_packet_header(packet_hex)
                            print(f"  Decoded header: version={version}, command={command}, txn_id={txn_id}, data={data.hex()}")

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
                            elif command and command[0] == 'C':
                                # Configuration request command
                                print(f"  Received '{command}' command, sending configuration packet")
                                # Use the received transaction ID for the response
                                config_packet = ConfigPacket(imei, server_address, reporting_interval, txn_id)
                                send('Requested Configuration', config_packet)
                                # No need to wait for acknowledgment here as we're already in the URC handler
                            elif command and command[0] == 'W':
                                # Write configuration command
                                print(f"  Received '{command}' command, updating configuration")

                                # Decode configuration payload into ConfigPacket
                                try:
                                    decoded_cfg = ConfigPacket.decode(imei, txn_id, data)
                                    server_address = decoded_cfg.server_address
                                    reporting_interval = decoded_cfg.reporting_interval
                                    reading_interval = decoded_cfg.reading_interval
                                except Exception as e:
                                    print(f"  Failed to decode configuration payload: {e}")
                                    # Keep existing config, but acknowledge with current config
                                print(f"  Configuration updated: server={server_address}, reporting_interval={reporting_interval}, reading_interval={reading_interval}")

                                config_packet = ConfigPacket(imei, server_address, reporting_interval, reading_interval, txn_id)
                                send('Configuration Updated', config_packet)
                                # No need to wait for acknowledgment here as we're already in the URC handler
                            elif command and command.startswith('U+'):
                                # Update request command
                                print(f"  Received '{command}' update request")
                                try:
                                    update_req = UpdateRequestPacket.decode(imei, txn_id, data)
                                    print(f"  UpdateRequest: component={update_req.component}, url={update_req.url}, args={update_req.arguments}")
                                    # Start simulated update in a separate thread

                                    Thread(target=component_update, args=(update_req, txn_id), daemon=True).start()
                                except Exception as e:
                                    print(f"  Failed to decode/process UpdateRequest: {e}")
                                # No ack wait here
                            else:
                                print(f"Ignoring command '{command}', not supported (only 'C', 'W' and 'U+' commands are supported)")
                    print("*" * 50)
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Exiting gracefully...")
        # Perform any necessary cleanup here
        term.stopping = True
        term.ser.close()
        print("Goodbye!")

ackHandler = Thread(target=ack_handler_thread, daemon=True)
ackHandler.start()

# Send Power On packet
txn_id = next_transaction_id()
power_on_packet = PowerOnPacket(imei, txn_id, customer_id, software_version, modem_version, network[0:3], network[3:6], rat)
send('Power On', power_on_packet)
wait_for_ack(txn_id)

# Send initial configuration packet
txn_id = next_transaction_id()
config_packet = ConfigPacket(imei, server_address, reporting_interval, reading_interval, txn_id)
send('Initial Configuration', config_packet)
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

            sensor_data = SensorDataMulti(battery, rssi, first_reading, int(reading_interval), records)
            if get_config('location.type') == 'simulated':
                lat, lon = sensors.read_loc()
                loc = LocationData.gnss(lat, lon)
            else:
                cell = sensors.read_serving_cell(term)
                loc = LocationData.cell(cell['mcc'], cell['mnc'], cell['lac'], cell['cell_id'], cell['rssi'])

            telemetry_packet = TelemetryPacket(imei, timestamp, txn_id, loc, sensor_data)
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
                loc = LocationData.gnss(lat, lon)
            else:
                cell = sensors.read_serving_cell(term)
                loc = LocationData.cell(cell['mcc'], cell['mnc'], cell['lac'], cell['cell_id'], cell['rssi'])

            # MotionStart uses NullSensorData (type 0, version 0)
            mstart_sd = SensorDataNull()
            mstart = MotionStartPacket(imei, timestamp, txn_id, loc, mstart_sd)
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
                loc = LocationData.gnss(lat, lon)
            else:
                cell = sensors.read_serving_cell(term)
                loc = LocationData.cell(cell['mcc'], cell['mnc'], cell['lac'], cell['cell_id'], cell['rssi'])

            # MotionStop uses MotionSensorData (type 3) with battery, rssi, steps
            mstop_sd = SensorDataSteps(battery=battery, rssi=rssi, steps=steps)
            mstop = MotionStopPacket(imei, timestamp, txn_id, loc, mstop_sd)
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
