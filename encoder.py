"""
Binary packet encoder/decoder for the Murata 1SC EVK Low-Powered Tracker Demo.

This module provides support utilities and re-exports packet and data classes.

All multi-byte values are encoded in big-endian format.
"""

import struct

def encode_var_string(input_str: str) -> bytes:
    """
    Encode a variable length string with a length byte prefix.

    Args:
        input_str (str): The string to encode

    Returns:
        bytes: The encoded string with length byte prefix
    """
    # Convert string to ASCII bytes
    bytes_data = input_str.encode('ascii')

    # Ensure length doesn't exceed 255 bytes (max value for uint8)
    if len(bytes_data) > 255:
        bytes_data = bytes_data[:255]  # Truncate if too long

    # Add length byte before the string
    return struct.pack('>B', len(bytes_data)) + bytes_data


