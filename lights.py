import socket
import struct
import time
import numpy as np
import cv2
import random
import os


class KnobReader:
    """
    This defines the class for the knob, allowing for voltage to be read from it.
    """

    def __init__(self, initial_value, ser: "serial.Serial"):
        self.ser = ser
        self.last_values = (initial_value, initial_value)
        self.waiting = False
        self.buffer = [(initial_value, initial_value)] * 10

    def read(self):
        # Haven't sent a read command: send one and return hold value.
        if not self.waiting:
            self.ser.write(b"\n")
            self.waiting = True
            return self.last_values
        # Otherwise, we're waiting for an entire line to come back.

        # If not enough bytes are ready, return the hold value.
        if self.ser.in_waiting < 12:
            return self.last_values

        line = self.ser.readline()

        try:
            values = line.split(b"\t")
            retval = int(values[0]), int(values[1])
        except ValueError:
            print(f"invalid value(s) in {line}")
            retval = (0, 0)

        self.waiting = False
        self.last_values = retval
        return retval

    def buffered_read(self) -> tuple[int, int]:
        result = self.read()
        self.buffer.pop()
        self.buffer.insert(0, result)
        return tuple(m // len(self.buffer) for m in map(sum, zip(*self.buffer)))

    @staticmethod
    def voltage_to_value(voltage: float) -> float:
        """
        This function takes an input between 0 and 2.8, and outputs a value between 0 and 1, with 1 being 2.8V and 0 being 0.05V
        """

        voltage = voltage * 3.3 / (65535)
        if voltage > 2.8:
            voltage = 2.8
        if voltage < 0.05:
            voltage = 0.05
        return (voltage - 0.05) / 2.75

    def get_knob_values(self) -> tuple[float, float]:
        return tuple(map(self.__class__.voltage_to_value, self.buffered_read()))


# gamma correction
# fmt: off
GAMMA = np.array([
    0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
    0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  1,  1,  1,  1,
    1,  1,  1,  1,  1,  1,  1,  1,  1,  2,  2,  2,  2,  2,  2,  2,
    2,  3,  3,  3,  3,  3,  3,  3,  4,  4,  4,  4,  4,  5,  5,  5,
    5,  6,  6,  6,  6,  7,  7,  7,  7,  8,  8,  8,  9,  9,  9, 10,
    10, 10, 11, 11, 11, 12, 12, 13, 13, 13, 14, 14, 15, 15, 16, 16,
    17, 17, 18, 18, 19, 19, 20, 20, 21, 21, 22, 22, 23, 24, 24, 25,
    25, 26, 27, 27, 28, 29, 29, 30, 31, 32, 32, 33, 34, 35, 35, 36,
    37, 38, 39, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 50,
    51, 52, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 66, 67, 68,
    69, 70, 72, 73, 74, 75, 77, 78, 79, 81, 82, 83, 85, 86, 87, 89,
    90, 92, 93, 95, 96, 98, 99, 101, 102, 104, 105, 107, 109, 110, 112, 114,
    115, 117, 119, 120, 122, 124, 126, 127, 129, 131, 133, 135, 137, 138, 140, 142,
    144, 146, 148, 150, 152, 154, 156, 158, 160, 162, 164, 167, 169, 171, 173, 175,
    177, 180, 182, 184, 186, 189, 191, 193, 196, 198, 200, 203, 205, 208, 210, 213,
    215, 218, 220, 223, 225, 228, 231, 233, 236, 239, 241, 244, 247, 249, 252, 255
])
# fmt: on


def sp_noise_mask(shape: tuple[int, int], prob):
    mask = np.zeros(shape, np.int8)
    thres = 1 - prob
    for i in range(shape[0]):
        for j in range(shape[1]):
            rdn = random.random()
            if rdn < prob:
                mask[i, j] = -1
            elif rdn > thres:
                mask[i, j] = 1
            else:
                mask[i, j] = 0
    return mask


def dnrgb_header(wait_time: int, start_index: int) -> bytes:
    """
    This function creates the header for the dnrgb protocol
    """

    if wait_time > 255:
        raise ValueError("Wait time must be within 0-255")
    if start_index > 2**16 - 1:
        raise ValueError("Start index must be a nonnegative 16-bit number")
    return struct.pack(">BBH", DNRGB_PROTOCOL_VALUE, wait_time, start_index)


def send_rgb(rgb_values, start_index=0):
    """
    This function sends the rgb values to the esp32
    """

    byte_string = dnrgb_header(5, start_index) + bytes(rgb_values)

    sock.sendto(byte_string, server)


def noise_effect(frame: "cv2.Mat", value: float) -> "np.ndarray":
    noise_shape = frame.shape[:2]
    if value < 0.83:
        return sp_noise_mask(noise_shape, value / 3)
    else:
        return np.ones(noise_shape, np.int8)


def hue_to_rgb(hue: int):
    return cv2.cvtColor(
        np.expand_dims(np.array([hue, 255, 255], np.uint8), axis=(0, 1)),
        cv2.COLOR_HSV2RGB,
    )[0, 0]


def hue_effect(frame, noise: "np.ndarray", value: float) -> "cv2.Mat":
    HUE_THRESHOLD = 0.1
    RAINBOW_THRESHOLD = 0.9

    low = 0
    if value < HUE_THRESHOLD:
        high = 255
    elif value < RAINBOW_THRESHOLD:
        hue = (value - HUE_THRESHOLD) / (RAINBOW_THRESHOLD - HUE_THRESHOLD)
        high = hue_to_rgb(round(hue * 255))
    else:
        CYCLE_TIME = 10
        cycle_position = (time.monotonic() / CYCLE_TIME) % 1
        hue = cycle_position
        high = hue_to_rgb(round(hue * 255))

    frame[noise == -1] = low
    frame[noise == 1] = high
    return frame


def crop_square(frame: "cv2.Mat") -> "cv2.Mat":
    h, w, _ = frame.shape
    assert w > h
    diff = w - h
    edge = diff // 2
    frame = frame[:, edge:-edge, :]
    h, w, _ = frame.shape
    assert h == w
    return frame


def zoom(frame: "cv2.Mat") -> "cv2.Mat":
    l, _, _ = frame.shape
    l_final = round(l / 1.3)
    to_remove = l - l_final
    return frame[to_remove:, (to_remove // 2) : -(to_remove // 2), :]


def start_cam(x, y):
    """
    This function takes a camera snapshot, compresses it, adds effects to it, and sends it to the esp32
    """

    webcam = cv2.VideoCapture(0)
    webcam.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    webcam.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
    webcam.set(cv2.CAP_PROP_BRIGHTNESS, 140)
    webcam.set(cv2.CAP_PROP_GAIN, 40)

    webcam.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3)
    webcam.set(cv2.CAP_PROP_FOCUS, 170)

    frame_count = 0
    start_time = time.time()
    while True:
        frame_count += 1
        if frame_count == 60:
            frame_count = 0
            print("frame time for 60:", time.time() - start_time)
            start_time = time.time()

        frame: "cv2.Mat"
        ret, frame = webcam.read()

        frame = crop_square(frame)
        frame = zoom(frame)

        frame = cv2.resize(frame, (x, y))

        frame[:, :, :] = frame[:, ::-1, :]

        frame = cv2.LUT(frame, GAMMA)

        frame = frame.astype(np.uint8)

        if knob_reader is not None:
            knob1, knob2 = knob_reader.get_knob_values()

            noise = noise_effect(frame, knob1)
            frame = hue_effect(frame, noise, knob2)

        # Get input orientation
        orientation = 3

        # Rotate the frame by 90 degrees based on user input
        if orientation == 1:
            frame = np.rot90(frame)
        elif orientation == 2:
            frame = np.rot90(frame, 2)
        elif orientation == 3:
            frame = np.rot90(frame, 3)

        RING_LIGHT_ON = True
        if RING_LIGHT_ON:
            RING_LIGHT_BRIGHTNESS = 255
            RING_LIGHT_VALUE = (RING_LIGHT_BRIGHTNESS,) * 3
            FRAME_WIDTH = 3

            frame[:FRAME_WIDTH, :] = RING_LIGHT_VALUE
            frame[-FRAME_WIDTH:, :] = RING_LIGHT_VALUE
            frame[:, :FRAME_WIDTH] = RING_LIGHT_VALUE
            frame[:, -FRAME_WIDTH:] = RING_LIGHT_VALUE

        send_quadrant(frame)


def send_quadrant(frame: "cv2.Mat"):
    QUADRANT_LEADING_LEDS = [1, 1, 1, 1]

    [[q1, q2], [q3, q4]] = [np.split(half, 2, axis=1) for half in np.split(frame, 2)]
    quadrants: list["np.ndarray"] = [q1, q2, q3, q4]

    for q in quadrants:
        q[1::2, :] = q[1::2, ::-1]

    quadrants = [q.reshape(-1, *q.shape[2:]) for q in quadrants]

    quadrants = [
        np.pad(q, ((n_leading, 0), (0, 0)), constant_values=0)
        for (n_leading, q) in zip(QUADRANT_LEADING_LEDS, quadrants)
    ]

    positions = [0] + np.cumsum([q.shape[0] for q in quadrants[:-1]]).tolist()

    quadrants = [q.flatten() for q in quadrants]

    for q, pos in zip(quadrants, positions):
        send_rgb(q, pos)


if __name__ == "__main__":
    if os.path.exists("/dev/ttyACM0"):
        import serial

        ser = serial.Serial("/dev/ttyACM0", 115200)
        time.sleep(0.001)

        ser = serial.Serial("/dev/ttyACM0", 115200)

        # initializes knob
        knob_reader = KnobReader(initial_value=0, ser=ser)
    else:
        knob_reader = None
        print("no serial detected, knobs will NOT be read")

    # this sets up network things for communication to the ESP32
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_address = "4.3.2.1"
    server_port = 21324
    server = (server_address, server_port)
    # this is the protocol # for the dnrgb protocol
    DNRGB_PROTOCOL_VALUE = 4

    print("Application started")
    start_cam(42, 42)
