import struct
import unittest

from pm25.pms5003 import ChecksumError, PMS5003, SensorTransportError
from pm25.sensor_sht31 import SHT31


class FakeSerial:
    def __init__(self, data: bytes) -> None:
        self.data = bytearray(data)

    def read(self, size: int) -> bytes:
        out = bytes(self.data[:size])
        del self.data[:size]
        return out


class FailingSerial:
    def read(self, size: int) -> bytes:
        raise OSError("UART disconnected")


def frame(*, valid_checksum: bool = True) -> bytes:
    header = bytes((0x42, 0x4D, 0x00, 0x1C))
    values = [1, 2, 3, 4, 5, 6, 30, 20, 10, 5, 2, 1, 0]
    body = struct.pack(">13H", *values)
    checksum = sum(header) + sum(body)
    if not valid_checksum:
        checksum += 1
    return header + body + struct.pack(">H", checksum)


class SensorProtocolTests(unittest.TestCase):
    def test_pms5003_decodes_atmospheric_and_particle_values(self) -> None:
        sensor = PMS5003.__new__(PMS5003)
        sensor._serial = FakeSerial(frame())
        sensor.read_timeout = 0.1

        reading = sensor.read()

        self.assertEqual(reading["pm2_5_atm"], 5)
        self.assertEqual(reading["pm10_atm"], 6)
        self.assertEqual(reading["n0_3"], 30)

    def test_pms5003_rejects_bad_checksum(self) -> None:
        sensor = PMS5003.__new__(PMS5003)
        sensor._serial = FakeSerial(frame(valid_checksum=False))
        sensor.read_timeout = 0.1

        with self.assertRaises(ChecksumError):
            sensor.read()

    def test_pms5003_rejects_unexpected_frame_length(self) -> None:
        sensor = PMS5003.__new__(PMS5003)
        sensor._serial = FakeSerial(bytes((0x42, 0x4D, 0x00, 0x20)))
        sensor.read_timeout = 0.1

        with self.assertRaisesRegex(ChecksumError, "frame length"):
            sensor.read()

    def test_pms5003_wraps_uart_transport_errors(self) -> None:
        sensor = PMS5003.__new__(PMS5003)
        sensor._serial = FailingSerial()
        sensor.read_timeout = 0.1

        with self.assertRaisesRegex(SensorTransportError, "UART disconnected"):
            sensor.read()

    def test_sht31_crc_reference_vector(self) -> None:
        self.assertEqual(SHT31._crc([0xBE, 0xEF]), 0x92)


if __name__ == "__main__":
    unittest.main()