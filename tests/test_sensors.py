import struct
import sys
import types
import unittest
from unittest import mock

from pm25 import pms5003

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


class _FakeV1Line:
    def __init__(self) -> None:
        self.values: list[int] = []
        self.request_kwargs: dict = {}
        self.released = False

    def request(self, **kwargs) -> None:
        self.request_kwargs = kwargs

    def set_value(self, value: int) -> None:
        self.values.append(value)

    def release(self) -> None:
        self.released = True


class _FakeV1Chip:
    instances: list["_FakeV1Chip"] = []

    def __init__(self, path: str) -> None:
        self.path = path
        self.line_no: int | None = None
        self.line = _FakeV1Line()
        self.closed = False
        _FakeV1Chip.instances.append(self)

    def get_line(self, n: int) -> _FakeV1Line:
        self.line_no = n
        return self.line

    def close(self) -> None:
        self.closed = True


class _FakeV2Request:
    def __init__(self) -> None:
        self.values: list[tuple[int, str]] = []
        self.released = False

    def set_value(self, line: int, value: str) -> None:
        self.values.append((line, value))

    def release(self) -> None:
        self.released = True


class GpiodOutputTests(unittest.TestCase):
    def test_make_output_none_pin(self) -> None:
        self.assertIsNone(pms5003.make_output(None))

    def test_make_output_string_pin_without_gpiod(self) -> None:
        with mock.patch.object(pms5003, "gpiod", None), self.assertLogs("pm25.pms5003", "WARNING"):
            self.assertIsNone(pms5003.make_output("gpiochip3:8"))

    def test_make_output_int_pin_without_gpiozero(self) -> None:
        with mock.patch.object(pms5003, "OutputDevice", None), self.assertLogs("pm25.pms5003", "WARNING"):
            self.assertIsNone(pms5003.make_output(22))

    def test_v1_api(self) -> None:
        fake = types.SimpleNamespace(Chip=_FakeV1Chip, LINE_REQ_DIR_OUT="out")
        _FakeV1Chip.instances.clear()
        with mock.patch.object(pms5003, "gpiod", fake):
            out = pms5003.make_output("gpiochip3:8", initial_value=False)
            self.assertIsInstance(out, pms5003.GpiodOutput)
            out.on()
            out.off()
            out.close()
            out.on()  # no-op after close
        chip = _FakeV1Chip.instances[0]
        self.assertEqual(chip.path, "/dev/gpiochip3")
        self.assertEqual(chip.line_no, 8)
        self.assertEqual(chip.line.request_kwargs["default_vals"], [0])
        self.assertEqual(chip.line.request_kwargs["type"], "out")
        self.assertEqual(chip.line.values, [1, 0])
        self.assertTrue(chip.line.released)
        self.assertTrue(chip.closed)

    def test_v2_api(self) -> None:
        request = _FakeV2Request()
        calls: list[tuple] = []

        def request_lines(path, consumer, config):
            calls.append((path, consumer, config))
            return request

        fake_line = types.SimpleNamespace(
            Direction=types.SimpleNamespace(OUTPUT="output"),
            Value=types.SimpleNamespace(ACTIVE="active", INACTIVE="inactive"),
        )
        fake = types.SimpleNamespace(
            request_lines=request_lines,
            LineSettings=lambda **kw: kw,
            line=fake_line,
        )
        with mock.patch.object(pms5003, "gpiod", fake), mock.patch.dict(
            sys.modules, {"gpiod": fake, "gpiod.line": fake_line}
        ):
            out = pms5003.GpiodOutput("/dev/gpiochip0:12")
            out.off()
            out.on()
            out.close()
        path, consumer, config = calls[0]
        self.assertEqual(path, "/dev/gpiochip0")
        self.assertEqual(consumer, "pm25")
        self.assertEqual(config, {12: {"direction": "output", "output_value": "active"}})
        self.assertEqual(request.values, [(12, "inactive"), (12, "active")])
        self.assertTrue(request.released)


if __name__ == "__main__":
    unittest.main()