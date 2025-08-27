class PacketDecoder:
    """Utility class for decoding packets"""

    @staticmethod
    def parse_response_data(data_str):
        """
        Parse the response data string and extract the 4th parameter.
        Example input: "1,4,0,"01410001","52.59.84.1",10104"

        Args:
            data_str (str): The response data string

        Returns:
            str or None: The 4th parameter (e.g., "01410001") or None if not found
        """
        try:
            # Split by commas, but respect quoted strings
            parts = []
            current_part = ""
            in_quotes = False

            for char in data_str:
                if char == '"':
                    in_quotes = not in_quotes
                    current_part += char
                elif char == ',' and not in_quotes:
                    parts.append(current_part)
                    current_part = ""
                else:
                    current_part += char

            # Add the last part
            if current_part:
                parts.append(current_part)

            # The 4th parameter is at index 3 (0-based indexing)
            if len(parts) >= 4:
                # Remove quotes if present
                fourth_param = parts[3].strip('"')
                return fourth_param
            else:
                print(f"Warning: Could not extract 4th parameter from '{data_str}'")
                return None
        except Exception as e:
            print(f"Error parsing response data: {e}")
            return None

    @staticmethod
    def decode_packet_header(hex_str):
        """
        Decode the packet header from a hex string.
        The header format is: <ver><cmd1><cmd2><txnId><imei>

        Args:
            hex_str (str): The hex string to decode

        Returns:
            tuple: A tuple of (version, command, transaction_id, remainder_bytes) or (None, None, None) on error
        """
        try:
            # Convert hex string to bytes
            data = bytes.fromhex(hex_str)

            # Extract version (first byte)
            version = data[0] if len(data) > 0 else None

            # Extract command (second and third bytes as ASCII characters)
            if len(data) > 2:
                cmd1 = chr(data[1])
                cmd2 = chr(data[2])
                command = cmd1 + cmd2
            else:
                command = None

            # Extract transaction ID (bytes 3-4 as an integer, using big-endian)
            txn_id = int.from_bytes(data[3:5], byteorder='big') if len(data) > 4 else None

            # Extract the remaining data
            data = data[5:]
            return (version, command, txn_id, data)
        except Exception as e:
            print(f"Error decoding packet header: {e}")
            return (None, None, None)


class DataReader:
    """
    Utility class for sequentially reading data from a byte array.

    This class provides methods for reading different data types from a byte array,
    advancing an internal index after each read operation to allow for sequential reading.

    All multi-byte values are decoded using big-endian format.
    """

    def __init__(self, data):
        """
        Initialize a DataReader with a byte array.

        Args:
            data (bytes or bytearray): The byte array to read from
        """
        self.data = data
        self.position = 0

    def read_var_string(self):
        """
        Read a variable-length string from the byte array.

        Reads 1 byte with the length of the string, followed by the string bytes.
        Advances the internal position by the total number of bytes read.

        Returns:
            str: The decoded string

        Raises:
            IndexError: If there is not enough data to read the string
        """
        # Check if there's enough data for the length byte
        if self.position >= len(self.data):
            raise IndexError("Not enough data to read string length")

        # Read the length byte
        length = self.data[self.position]
        self.position += 1

        # Check if there's enough data for the string
        if self.position + length > len(self.data):
            raise IndexError(f"Not enough data to read string of length {length}")

        # Read the string bytes
        string_bytes = self.data[self.position:self.position + length]
        self.position += length

        # Decode the string as ASCII
        return string_bytes.decode('ascii')

    def read_int4(self):
        """
        Read a 4-byte integer from the byte array.

        Reads 4 bytes and interprets them as a big-endian 32-bit integer.
        Advances the internal position by 4 bytes.

        Returns:
            int: The decoded integer

        Raises:
            IndexError: If there is not enough data to read the integer
        """
        # Check if there's enough data for the integer
        if self.position + 4 > len(self.data):
            raise IndexError("Not enough data to read 4-byte integer")

        # Read the integer bytes
        int_bytes = self.data[self.position:self.position + 4]
        self.position += 4

        # Decode the integer as big-endian
        return int.from_bytes(int_bytes, byteorder='big')
