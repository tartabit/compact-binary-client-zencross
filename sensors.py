import random


def read_temp():
    """
    Simulate temperature reading from a sensor.

    Returns:
        float: A random temperature value between 18.0 and 24.0°C, rounded to 1 decimal place.
    """
    t = random.uniform(18.0, 24.0)
    return round(t, 1)


def read_hum():
    """
    Simulate humidity reading from a sensor.

    Returns:
        float: A random humidity value between 35.0 and 50.0%, rounded to 1 decimal place.
    """
    t = random.uniform(35.0, 50.0)
    return round(t, 1)

# Starting point (Ottawa, Canada)
last_lat = 45.448803450183924
last_lon = -75.63533774831912

def read_loc():
    global last_lat, last_lon
    """
    Simulate GPS location reading with random movement and eastward bias.

    Updates the global last_lat and last_lon variables with a small random change,
    with a bias toward eastward movement.

    Returns:
        tuple: A tuple of (latitude, longitude) coordinates, rounded to 6 decimal places.
    """
    # Random movement with eastward bias
    lat_change = random.uniform(-0.0001, 0.0001)
    lon_change = random.uniform(0.0001, 0.0003)  # Eastward bias

    last_lat += lat_change
    last_lon += lon_change

    return (round(last_lat, 6), round(last_lon, 6))

battery_level = 100
def read_battery():
    global battery_level
    """
    Simulate battery level reading.

    Returns:
        float: 50% chance to reduce battery by 1, reset to 100 if too low.
    """
    if random.uniform(1.0, 100.0)>50.0:
        battery_level =- 1

    if battery_level < 5:
        battery_level = 100
    # Simulate battery level between 70% and 100%
    return battery_level

def read_rssi(term):
    rsp = term.send_command('AT+CSQ')
    rssi = int(rsp.split[0]) if rsp.success else 0xFF
    return rssi

def read_steps(duration_seconds: int = 60) -> int:
    """
    Simulate a step count for the motion window.
    Roughly 1-2 steps per second walking.
    """
    rate = random.uniform(0.8, 1.8)
    steps = int(rate * max(1, duration_seconds))
    # Add some noise
    steps += random.randint(-5, 5)
    return max(0, steps)

def read_serving_cell(term):
    rsp = term.send_command('AT%MEAS="95"')
    if not rsp.success:
        print(f"Error reading serving cell: {rsp}")
        return None
    return {
        'cell_id': rsp.split[0].removeprefix("ECID:"),
        'lac': rsp.split[5],
        'mcc': rsp.split[3],
        'mnc': rsp.split[4],
        'rssi': int(rsp.split[9]),
    }
