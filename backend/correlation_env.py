import math


def drift_vector_ms(wind, current):
    vx = vy = 0.0
    if wind:
        to = math.radians((wind["direction_deg"] + 180) % 360)
        vx += 0.03 * wind["speed_ms"] * math.sin(to)
        vy += 0.03 * wind["speed_ms"] * math.cos(to)
    if current:
        d = math.radians(current["direction_deg"])
        vx += current["speed_ms"] * math.sin(d)
        vy += current["speed_ms"] * math.cos(d)
    return vx, vy
