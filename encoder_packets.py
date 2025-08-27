import struct
from encoder import encode_var_string

class Packet:

    def __init__(self, command, imei, transaction_id=0, version=1):
        """
        Initialize a packet with command, IMEI, and transaction ID

        Args:
            command (str): Two character command identifier (can be a single character with a null)
            imei (str): Device IMEI number
            transaction_id (int, optional): Sequence number (0-65535). Defaults to 0.
        """
        # Ensure command is exactly 2 characters, pad with null if needed
        if len(command) == 1:
            self.command = command + '\0'  # Pad with null character
        elif len(command) >= 2:
            self.command = command[:2]  # Truncate to 2 characters if longer
        else:
            self.command = '\0\0'  # Default to null characters if empty

        self.imei = imei
        self.transaction_id = transaction_id
        self.version = version

    def build_header(self):
        """
        Build the common packet header:
        - Version: 1 byte (uint8, value 1)
        - Command: 2 bytes (ASCII characters)
        - Transaction ID: 2 bytes (uint16)
        - IMEI: 15 bytes (ASCII)

        Returns:
            bytes: The packet header
        """
        # Convert IMEI to bytes
        imei_bytes = self.imei.encode('ascii')

        # Pack the header (using big-endian format for all values)
        header = struct.pack('>BBB', 
                            self.version,
                            ord(self.command[0]),  # First command character
                            ord(self.command[1])   # Second command character
                            ) + struct.pack('>H', self.transaction_id) + imei_bytes
        return header

    def to_bytes(self):
        """
        Convert packet to bytes (to be implemented by subclasses)

        Returns:
            bytes: The complete packet as bytes
        """
        raise NotImplementedError("Subclasses must implement to_bytes()")

    def print(self, packet_type):
        packet_bytes = self.to_bytes()
        print("v" * 50)
        print(f"  Type: {packet_type}")
        print(f"  Transaction ID: {self.transaction_id}")
        print(f"  Packet: {packet_bytes.hex()}")
        print(f"  Packet size: {len(packet_bytes)} bytes")
        print("^" * 50)

    def send(self, packet_type, term):
        packet_bytes = self.to_bytes()
        term.send_command(f'AT%SOCKETDATA="SEND",1,{len(packet_bytes)},"{packet_bytes.hex()}"')
        self.print(packet_type)


class TelemetryPacket(Packet):
    """
    Telemetry packet (command 'T\0' or 'T' padded with null) containing device telemetry data

    Packet structure:
    - Version: 1 byte (uint8, value 1)
    - Command: 2 bytes (ASCII characters, e.g., 'T\0')
    - Transaction ID: 2 bytes (uint16)
    - IMEI: 15 bytes (ASCII)
    - Timestamp: 4 bytes (uint32)
    - LocationData: variable length structure
    - SensorData: variable length structure
    """

    def __init__(self, imei, timestamp, transaction_id, location_data, sensor_data):
        """
        Initialize a telemetry packet

        Args:
            imei (str): Device IMEI number
            timestamp (int): Unix timestamp in seconds
            transaction_id (int): Sequence number (0-65535)
            location_data (LocationData): The encoded location data (GNSS or CELL)
            sensor_data (ISensorData): Any object implementing the SensorData interface (to_bytes, describe)
        """
        super().__init__('T', imei, transaction_id, 1)
        self.timestamp = timestamp
        self.location_data = location_data
        self.sensor_data = sensor_data

    def to_bytes(self):
        """
        Convert telemetry packet to bytes

        Returns:
            bytes: The complete telemetry packet as bytes
        """
        # Build header
        header = self.build_header()

        # Encode location data
        loc_bytes = self.location_data.to_bytes()

        # Encode sensor data
        if not hasattr(self.sensor_data, 'to_bytes') or not callable(getattr(self.sensor_data, 'to_bytes')):
            raise TypeError("sensor_data must implement to_bytes() method (SensorData interface)")
        sensor_bytes = self.sensor_data.to_bytes()

        # Pack the telemetry data
        data = struct.pack('>I', self.timestamp) + \
               loc_bytes + \
               sensor_bytes

        return header + data

    def print(self, packet_type):
        packet_bytes = self.to_bytes()
        print("v" * 50)
        print(f"  Type: {packet_type}")
        print(f"  Transaction ID: {self.transaction_id}")
        loc_str = self.location_data.describe()
        try:
            sensor_str = self.sensor_data.describe()
        except Exception:
            sensor_str = str(self.sensor_data)
        print(f"  Location: {loc_str}")
        print(f"  Sensors: {sensor_str}")
        print(f"  Packet: {packet_bytes.hex()}")
        print(f"  Packet size: {len(packet_bytes)} bytes")
        print("^" * 50)


class ConfigPacket(Packet):
    """
    Configuration packet (command 'C\0' or 'C' padded with null) containing device configuration

    Packet structure:
    - Version: 1 byte (uint8, value 1)
    - Command: 2 bytes (ASCII characters, e.g., 'C\0')
    - Transaction ID: 2 bytes (uint16)
    - IMEI: 15 bytes (ASCII)
    - Server address length: 1 byte (uint8)
    - Server address: variable length (ASCII string, length specified by previous field)
    - Publish Interval: 4 bytes (uint32, seconds between publishes)
    - Reading Interval: 4 bytes (uint32, seconds between sensor readings)
    """

    def __init__(self, imei, server_address, reporting_interval, reading_interval, transaction_id=0):
        """
        Initialize a configuration packet

        Args:
            imei (str): Device IMEI number
            server_address (str): Server address in format "hostname:port"
            reporting_interval (int): Seconds between publishes
            transaction_id (int, optional): Sequence number (0-65535). Defaults to 0.
        """
        super().__init__('C', imei, transaction_id)
        self.server_address = server_address
        self.reporting_interval = reporting_interval
        self.reading_interval = reading_interval

    def to_bytes(self):
        """
        Convert configuration packet to bytes

        Returns:
            bytes: The complete configuration packet as bytes
        """
        # Build header
        header = self.build_header()

        # Encode server address as a variable length string
        address_with_length = encode_var_string(self.server_address)

        # Pack the configuration data
        data = address_with_length + struct.pack('>II', self.reporting_interval, self.reading_interval)  # 4 bytes: uint32 interval

        return header + data

    def print(self, packet_type):
        packet_bytes = self.to_bytes()
        print("v" * 50)
        print(f"  Type: {packet_type}")
        print(f"  Transaction ID: {self.transaction_id}")
        print(f"  Server: {self.server_address}")
        print(f"  Reporting Interval: {self.reporting_interval} seconds")
        print(f"  Reading Interval: {self.reading_interval} seconds")
        print(f"  Packet: {packet_bytes.hex()}")
        print(f"  Packet size: {len(packet_bytes)} bytes")
        print("^" * 50)


class PowerOnPacket(Packet):
    """
    Power On packet (command 'P+') sent when the device first starts up

    Packet structure:
    - Version: 1 byte (uint8, value 1)
    - Command: 2 bytes (ASCII characters 'P+')
    - Transaction ID: 2 bytes (uint16)
    - IMEI: 15 bytes (ASCII)
    - Customer ID: 4 bytes (uint32)
    - Software Version Length: 1 byte (uint8)
    - Software Version: Variable length (ASCII string, length specified by previous field)
    - Modem Version Length: 1 byte (uint8)
    - Modem Version: Variable length (ASCII string, length specified by previous field)
    - MCC Length: Variable length (ASCII string, length specified by previous field)
    - MNC Length: Variable length (ASCII string, length specified by previous field)
    - RAT: Variable length (ASCII string, length specified by previous field)
    """

    def __init__(self, imei, transaction_id, customer_id, software_version, modem_version, mcc, mnc, rat):
        """
        Initialize a power on packet

        Args:
            imei (str): Device IMEI number
            transaction_id (int): Sequence number (0-65535)
            software_version (str): Software version of the demo app
            modem_version (str): Modem firmware version
            mcc (str): Mobile Country Code (e.g., "228")
            mnc (str): Mobile Network Code (e.g., "01")
        """
        super().__init__('P+', imei, transaction_id, 1)
        self.customer_id = customer_id
        self.software_version = software_version
        self.modem_version = modem_version
        self.mcc = mcc
        self.mnc = mnc
        self.rat = rat

    def to_bytes(self):
        """
        Convert power on packet to bytes

        Returns:
            bytes: The complete power on packet as bytes
        """
        # Build header
        header = self.build_header()

        customer_id_bytes = bytes.fromhex(self.customer_id)

        # Encode software version and firmware version as variable length strings
        software_version_with_length = encode_var_string(self.software_version)
        modem_version_with_length = encode_var_string(self.modem_version)
        mcc_with_length = encode_var_string(self.mcc)
        mnc_with_length = encode_var_string(self.mnc)
        rat_with_length = encode_var_string(self.rat)

        data = customer_id_bytes + software_version_with_length + modem_version_with_length + mcc_with_length + mnc_with_length + rat_with_length

        return header + data

    def print(self, packet_type):
        packet_bytes = self.to_bytes()
        print("v" * 50)
        print(f"  Type: {packet_type}")
        print(f"  Transaction ID: {self.transaction_id}")
        print(f"  Software Version: {self.software_version}")
        print(f"  Modem Version: {self.modem_version}")
        print(f"  Network: MCC:{self.mcc}, MNC:{self.mnc}, RAT:{self.rat}")
        print(f"  Packet: {packet_bytes.hex()}")
        print(f"  Packet size: {len(packet_bytes)} bytes")
        print("^" * 50)
