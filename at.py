import queue
import threading

import serial
from threading import Thread, Event
import re

from serial import SerialException

debug = False

at_extractor_pattern = r'AT([\+\%][^=?]+)'
at_response_pattern = r'^([^:\r\n]+)'
at_urc_pattern = r'^%(\w+):(.+)$'

class AtUrc:
    urc = None
    data = None

    def __init__(self, urc, data):
        self.urc = urc
        self.data = data

    def __str__(self):
        return f"urc: {self.urc}\n\tdata: {self.data}"

class AtResponse:
    command = None
    success = False
    data = None
    split = None

    def __init__(self, command, success, data):
        self.command = command
        self.success = success
        self.data = data
        if isinstance(self.data, str):
            self.split = self.data.split(',')
            self.split = [s.replace('"', '') for s in self.split]

    def __str__(self):
        return f"command: {self.command}\n\tsuccess:{self.success}\n\tdata: {self.data}"

class AtTerminal:
    log = False
    def __init__(self, port, baudrate):
        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = baudrate
        self.reader = None
        self.stopping = False
        self.responseEvent = Event()
        self.responseData = None
        self.responseSuccess = False
        self.urcQueue = queue.Queue()

    def open(self):
        try:
            self.ser.open()
            print(f"++ port open: {self.ser.is_open}") if debug else None
            if self.ser.is_open:
                self.reader = Thread(target=self.read, daemon=True)
                self.reader.start()
        except serial.SerialException as e:
            print(f"++ error opening port: {e}") if debug else None
            return False
        return self.ser.is_open

    def read(self):
        while not self.stopping:
            while True:
                try:
                    line = self.ser.readline()
                    print(f"++ raw-read: {line}") if debug else None
                    if line == b'\r\n':
                        continue
                    elif line == b'OK\r\n':
                        self.responseSuccess = True
                        self.responseEvent.set()
                        continue
                    elif line == b'ERROR\r\n':
                        self.responseSuccess = False
                        self.responseEvent.set()
                        continue

                    print(f"++ read: {line}") if debug else None

                    line_string = line.decode('utf-8')

                    match = re.search(at_urc_pattern, line_string)
                    if match:
                        urc = match.group(1)
                        print(f"++ urc: {urc}") if debug else None
                        self.urcQueue.put(AtUrc(urc, match.group(2)))

                    parts = line_string.split(':', 1)
                    resp = parts[1].strip() if len(parts) > 1 else line_string.strip()
                    if self.responseData:
                        if isinstance(self.responseData, str):
                            self.responseData = [self.responseData]
                        self.responseData.append(resp)
                    else:
                        self.responseData = resp
                except SerialException as e:
                    print(f"++ read exception: {e}")
                    self.ser.close()
                    while True:
                        self.ser.open()
                        print(f"++ port re-opened: {self.ser.is_open}") if debug else None
                except Exception as e:
                    print(f"++ other exception: {e}")
                    exit(-1)



    def send_command(self, str):
        match = re.search(at_extractor_pattern, str)
        if str == 'ATE0':
            command = 'ATE0'
        elif match:
            command = match.group(1)
        else:
            command = None

        if command:
            self.responseEvent.clear()
            self.responseData = None
            self.responseSuccess = False

            output = bytes(f'{str}\r\n', 'utf-8')
            print(f'++ sending [{command}]: {output}') if debug else None
            self.ser.write(output)
            self.responseEvent.wait(timeout=5)
            print(f"++ success: {self.responseSuccess}, data: {self.responseData}") if debug else None
            atr = AtResponse(str, self.responseSuccess, self.responseData)
        else:
            output = bytes(f'{str}\r\n', 'utf-8')
            print(f'++ sending: {output}') if debug else None
            self.ser.write(output)
            atr = AtResponse(str, True, None)
        if self.log:
            print(atr)
        return atr

    def wait_for_urc(self):
        try:
            urc = self.urcQueue.get(True, 5)
            return urc
        except queue.Empty:
            print(f'++ timeout waiting for urc') if debug else None
            return None

    def __del__(self):
        self.stopping = True
        self.ser.close()
        if self.reader is not None:
            self.reader.join()