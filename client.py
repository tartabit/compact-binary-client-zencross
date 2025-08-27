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
import os
import time
from threading import Thread, Event

import at
import random
from config import get_config
from encoder_data import LocationData, SensorMultiData
from encoder_packets import TelemetryPacket, ConfigPacket, PowerOnPacket
from decoder import PacketDecoder, DataReader
import sensors

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
ack_event = Event()
last_ack_txn_id = None
def next_transaction_id():
    """
    Generate the next transaction ID, wrapping around at 65536.

    Returns:
        int: The next transaction ID.
    """
    global transaction_id
    transaction_id = (transaction_id + 1) % 65536
    return transaction_id

def wait_for_ack(txn_id=None, timeout=30):
    """
    Wait for an acknowledgment to be received before proceeding.

    This function waits until a URC with an 'A' command is received, or until the timeout expires.
    If txn_id is provided, it also checks that the acknowledgment matches the expected transaction ID.

    Args:
        txn_id (int, optional): The transaction ID to wait for. If None, any acknowledgment will be accepted.
        timeout (int, optional): Maximum time to wait in seconds. Defaults to 30.

    Returns:
        bool: True if an acknowledgment was received, False if a timeout occurred.
    """
    global ack_event, last_ack_txn_id

    # Clear the event before waiting
    ack_event.clear()

    # Wait for the event to be set with a timeout
    if ack_event.wait(timeout):
        # Event was set, check if the transaction ID matches (if provided)
        if txn_id is not None and last_ack_txn_id != txn_id:
            print(f"Warning: Received acknowledgment for transaction ID {last_ack_txn_id}, but expected {txn_id}")
            return False
        return True
    else:
        # Timeout occurred
        print(f"Warning: Timeout waiting for acknowledgment after {timeout} seconds")
        return False


# Initialize modem and get device information
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
                                # Set the acknowledgment event and store the transaction ID
                                global last_ack_txn_id
                                last_ack_txn_id = txn_id
                                ack_event.set()
                            elif command and command[0] == 'C':
                                # Configuration request command
                                print(f"  Received '{command}' command, sending configuration packet")
                                # Use the received transaction ID for the response
                                config_packet = ConfigPacket(imei, server_address, reporting_interval, txn_id)
                                config_packet.send('Requested Configuration', term)
                                # No need to wait for acknowledgment here as we're already in the URC handler
                            elif command and command[0] == 'W':
                                # Write configuration command
                                print(f"  Received '{command}' command, updating configuration")

                                reader = DataReader(data)
                                new_server_address = reader.read_var_string()
                                new_reporting_interval = reader.read_int4()
                                new_reading_interval = reader.read_int4()

                                server_address = new_server_address
                                reporting_interval = new_reporting_interval
                                reading_interval = new_reading_interval

                                print(f"  Configuration updated: server={server_address}, reporting_interval={reporting_interval}, reading_interval={reading_interval}")

                                config_packet = ConfigPacket(imei, server_address, reporting_interval, reading_interval, txn_id)
                                config_packet.send('Configuration Updated', term)
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

# Send Power On packet
txn_id = next_transaction_id()
power_on_packet = PowerOnPacket(imei, txn_id, customer_id, software_version, modem_version, network[0:3], network[3:6], rat)
power_on_packet.send('Power On', term)
wait_for_ack(txn_id)

# Send initial configuration packet
txn_id = next_transaction_id()
config_packet = ConfigPacket(imei, server_address, reporting_interval, reading_interval, txn_id)
config_packet.send('Initial Configuration', term)
wait_for_ack(txn_id)

try:
    while True:

        # Increment transaction ID (wrap around at 65535)
        txn_id = next_transaction_id()

        # Get current data
        timestamp = int(time.time())
        battery = sensors.read_battery()
        rssi = sensors.read_rssi(term)

        
        # Build records of temperature/humidity for SensorMultiData
        # Number of records equals reporting_interval / reading_interval (integer)
        try:
            record_count = max(1, int(reporting_interval // reading_interval))
        except Exception:
            record_count = 1
        # Compute first_reading timestamp: subtract record_count * reading_interval and round down to nearest minute
        first_reading = timestamp - (record_count * reading_interval)
        first_reading = first_reading - (first_reading % 60)
        records = []
        for _ in range(record_count):
            records.append({
                'temperature': sensors.read_temp(),
                'humidity': sensors.read_hum(),
            })

        # Create telemetry packet
        sensor_data = SensorMultiData(battery, rssi, first_reading, reading_interval, records)
        if get_config('location.type')=="simulated":
            lat, lon = sensors.read_loc()
            loc = LocationData.gnss(lat, lon)
        else:
            cell = sensors.read_serving_cell(term)
            loc = LocationData.cell(cell['mcc'],cell['mnc'],cell['lac'], cell['cell_id'], cell['rssi'])
        telemetry_packet = TelemetryPacket(imei, timestamp, txn_id, loc, sensor_data)
        telemetry_packet.send('Telemetry', term)
        wait_for_ack(txn_id)

        # Wait before next transmission using the configured reporting interval
        print(f"Waiting for {reporting_interval} seconds before next transmission...")
        time.sleep(reporting_interval)
except KeyboardInterrupt:
    print("\nCtrl+C detected. Exiting gracefully...")
    # Perform any necessary cleanup here
    term.stopping = True
    term.ser.close()
    print("Goodbye!")
