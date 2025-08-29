import struct
from abc import ABC, abstractmethod
from encoder import encode_var_string

class LocationData:
    TYPE_GNSS = 1
    TYPE_CELL = 2

    def __init__(self, loc_type, *, latitude=None, longitude=None, mcc=None, mnc=None, lac=None, cell_id=None, rssi=None):
        self.loc_type = int(loc_type)
        self.latitude = latitude
        self.longitude = longitude
        self.mcc = mcc
        self.mnc = mnc
        self.lac = lac
        self.cell_id = cell_id
        self.rssi = rssi

    @staticmethod
    def gnss(latitude, longitude):
        return LocationData(LocationData.TYPE_GNSS, latitude=float(latitude), longitude=float(longitude))

    @staticmethod
    def cell(mcc, mnc, lac, cell_id, rssi):
        return LocationData(LocationData.TYPE_CELL, mcc=str(mcc), mnc=str(mnc), lac=str(lac), cell_id=str(cell_id), rssi=int(rssi))

    def to_bytes(self):
        # Type byte first
        if self.loc_type == LocationData.TYPE_GNSS:
            if self.latitude is None or self.longitude is None:
                raise ValueError("GNSS LocationData requires latitude and longitude")
            return struct.pack('>Bff', self.loc_type, float(self.latitude), float(self.longitude))
        elif self.loc_type == LocationData.TYPE_CELL:
            if None in (self.mcc, self.mnc, self.lac, self.cell_id) or self.rssi is None:
                raise ValueError("CELL LocationData requires mcc, mnc, lac, cell_id, and rssi")
            from_bytes = struct.pack('>B', self.loc_type)
            # Variable-length strings (ASCII) followed by 1-byte RSSI
            return (
                from_bytes
                + encode_var_string(self.mcc)
                + encode_var_string(self.mnc)
                + encode_var_string(self.lac)
                + encode_var_string(self.cell_id)
                + struct.pack('>b', int(self.rssi))
            )
        else:
            raise ValueError(f"Unknown LocationData type: {self.loc_type}")

    def describe(self):
        if self.loc_type == LocationData.TYPE_GNSS:
            return f"GNSS(lat={self.latitude}, lon={self.longitude})"
        elif self.loc_type == LocationData.TYPE_CELL:
            return f"CELL(mcc={self.mcc}, mnc={self.mnc}, lac={self.lac}, cell_id={self.cell_id}, rssi={self.rssi})"
        return f"UNKNOWN(type={self.loc_type})"


class SensorData:
    """
    Encapsulates sensor telemetry values with a type/version header and length-prefixed payload.

    Packet structure (when serialized):
    - sensor_type: 1 byte (uint8)
    - sensor_version: 1 byte (uint8)
    - sensor_length: 1 byte (uint8, number of payload bytes following)
    - payload:
      - temperature: 2 bytes (int16, value = temp*10)
      - battery: 1 byte (uint8, percentage)
      - rssi: 1 byte (uint8)
    """
    def __init__(self, sensor_type, temperature, battery, rssi, sensor_version=1):
        self.sensor_type = int(sensor_type)
        self.sensor_version = int(sensor_version)
        self.temperature = float(temperature)
        self.battery = int(battery)
        self.rssi = int(rssi)

    def to_bytes(self):
        # Build payload first
        payload = struct.pack('>HBB', int(self.temperature * 10), self.battery, self.rssi)
        header = struct.pack('>BBB', self.sensor_type, self.sensor_version, len(payload))
        return header + payload

    def describe(self):
        return f"Sensor(type={self.sensor_type}, ver={self.sensor_version}, temp={self.temperature}°C, batt={self.battery}%, rssi={self.rssi})"

class SensorMultiData:
    """
    Encapsulates sensor telemetry values with a type/version header and length-prefixed payload.

    Packet structure (when serialized):
    - sensor_type: 1 byte (uint8)
    - sensor_version: 1 byte (uint8)
    - sensor_length: 1 byte (uint8)
    - payload:
      - battery: 1 byte (uint8, percentage)
      - rssi: 1 byte (uint8)
      - first_record_time: 4 bytes (uint32)
      - record_interval: 2 bytes (uint16)
      - record_count: 1 byte (uint8)
        - temperature: 2 bytes (int16, value = temp*10)
        - humidity: 2 bytes (int16, value = humidity*10)
    """
    def __init__(self, battery, rssi, first_timestamp, interval, records):
        self.sensor_type = int(2)
        self.sensor_version = int(1)
        self.battery = int(battery)
        self.rssi = int(rssi)
        self.first_timestamp = first_timestamp
        self.interval = interval
        self.records = records
        self.battery = int(battery)
        self.rssi = int(rssi)

    def to_bytes(self):
        # Build payload: battery, rssi, first_timestamp, interval, record_count + records
        payload_header = struct.pack(
            '>BBIHB',
            self.battery,
            self.rssi,
            int(self.first_timestamp),
            int(self.interval),
            len(self.records)
        )

        # Each record is a dict: { 'temperature': float, 'humidity': float }
        # Encode as two int16 values (temp*10, humidity*10)
        records_bytes = bytearray()
        for rec in self.records:
            temp = int(round(float(rec['temperature']) * 10))
            hum = int(round(float(rec['humidity']) * 10))
            records_bytes += struct.pack('>hh', temp, hum)

        payload = payload_header + bytes(records_bytes)
        header = struct.pack('>BBB', self.sensor_type, self.sensor_version, len(payload))
        return header + payload

    def describe(self):
        rec_cnt = len(self.records) if self.records is not None else 0
        return (
            f"SensorMulti(type={self.sensor_type}, ver={self.sensor_version}, "
            f"batt={self.battery}%, rssi={self.rssi}, first_ts={self.first_timestamp}, "
            f"interval={self.interval}s, records={rec_cnt})"
        )


class NullSensorData:
    """
    Null/empty sensor data placeholder for events that carry no sensor values.

    Serialized as header with zero-length payload.
    - sensor_type: 1 byte (0)
    - sensor_version: 1 byte (0)
    - sensor_length: 1 byte (0)
    """
    def __init__(self):
        self.sensor_type = 0
        self.sensor_version = 0

    def to_bytes(self):
        # No payload
        return struct.pack('>BBB', self.sensor_type, self.sensor_version, 0)

    def describe(self):
        return f"SensorNull(type={self.sensor_type}, ver={self.sensor_version})"


class MotionSensorData:
    """
    Motion stop sensor data (type 3) carrying summary stats.

    Packet structure (when serialized):
    - sensor_type: 1 byte (uint8) = 3
    - sensor_version: 1 byte (uint8) = 1
    - sensor_length: 1 byte (uint8)
    - payload:
      - battery: 1 byte (uint8, percentage)
      - rssi: 1 byte (uint8)
      - steps: 4 bytes (int32)
    """
    def __init__(self, battery: int, rssi: int, steps: int, sensor_version: int = 1):
        self.sensor_type = 3
        self.sensor_version = int(sensor_version)
        self.battery = int(battery)
        self.rssi = int(rssi)
        self.steps = int(steps)

    def to_bytes(self):
        payload = struct.pack('>BBi', self.battery, self.rssi, self.steps)
        header = struct.pack('>BBB', self.sensor_type, self.sensor_version, len(payload))
        return header + payload

    def describe(self):
        return (
            f"SensorMotion(type={self.sensor_type}, ver={self.sensor_version}, "
            f"batt={self.battery}%, rssi={self.rssi}, steps={self.steps})"
        )
