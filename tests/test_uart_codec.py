"""Tests for uart_codec — CRC32 envelope (UART_PROTOCOL.md §Envelope)."""

import unittest

from smart_kosher.adapters import uart_decode, uart_encode


class EncodeTests(unittest.TestCase):
    def test_encode_produces_crc_space_json_newline(self):
        line = uart_encode({"version": 1, "type": "cmd", "op": "coordinator_start"})
        parts = line.decode("utf-8").split(" ", 1)
        self.assertEqual(2, len(parts))
        self.assertEqual(8, len(parts[0]))      # 8-char hex CRC
        self.assertTrue(parts[1].endswith("\n"))

    def test_known_coordinator_start_crc(self):
        # CRC pre-computed: python -c "import binascii,json; ..."
        msg = {
            "version": 1, "request_id": "r1", "command_id": "boot_start",
            "type": "cmd", "op": "coordinator_start", "payload": {},
        }
        line = uart_encode(msg).decode("utf-8")
        self.assertTrue(line.startswith("91bb5a42 "), line[:20])

    def test_known_sent_to_zigbee_ack_crc(self):
        msg = {
            "version": 1, "request_id": "r42",
            "command_id": "sch_001_2026-06-20_1830",
            "type": "ack", "status": "sent_to_zigbee",
        }
        line = uart_encode(msg).decode("utf-8")
        self.assertTrue(line.startswith("80c660bf "), line[:20])

    def test_known_boot_event_crc(self):
        msg = {
            "version": 1, "h2_event_id": 1,
            "type": "event", "op": "boot",
            "payload": {"boot_id": 7, "firmware_version": "0.1.0"},
        }
        line = uart_encode(msg).decode("utf-8")
        self.assertTrue(line.startswith("45c1c6c9 "), line[:20])

    def test_encode_decode_roundtrip(self):
        msg = {"version": 1, "type": "cmd", "op": "permit_join",
               "payload": {"duration_s": 60}}
        decoded = uart_decode(uart_encode(msg).decode("utf-8"))
        self.assertEqual(msg, decoded)

    def test_non_ascii_survives_roundtrip(self):
        msg = {"label": "מנורה"}
        decoded = uart_decode(uart_encode(msg).decode("utf-8"))
        self.assertEqual(msg, decoded)


class DecodeTests(unittest.TestCase):
    def test_good_line_returns_dict(self):
        line = uart_encode({"x": 1}).decode("utf-8")
        self.assertEqual({"x": 1}, uart_decode(line))

    def test_bytes_line_returns_dict(self):
        line = uart_encode({"x": 1})
        self.assertEqual({"x": 1}, uart_decode(line))

    def test_bad_crc_raises(self):
        line = uart_encode({"x": 1}).decode("utf-8")
        tampered = "00000000" + line[8:]          # wrong CRC
        with self.assertRaises(ValueError) as ctx:
            uart_decode(tampered)
        self.assertIn("bad_crc", str(ctx.exception))

    def test_tampered_body_raises(self):
        line = uart_encode({"x": 1}).decode("utf-8")
        crc, _, body = line.partition(" ")
        tampered = crc + " " + body.replace("1", "2")
        with self.assertRaises(ValueError):
            uart_decode(tampered)

    def test_missing_space_raises(self):
        with self.assertRaises(ValueError) as ctx:
            uart_decode("deadbeef")
        self.assertIn("bad_crc", str(ctx.exception))

    def test_non_hex_prefix_raises(self):
        with self.assertRaises(ValueError) as ctx:
            uart_decode("ZZZZZZZZ {}")
        self.assertIn("bad_crc", str(ctx.exception))

    def test_crc_prefix_must_be_eight_lowercase_hex_chars(self):
        for line in ("1 {}", "000000001 {}", "DEADBEEF {}", "+0000001 {}"):
            with self.subTest(line=line):
                with self.assertRaises(ValueError) as ctx:
                    uart_decode(line)
                self.assertIn("bad_crc", str(ctx.exception))

    def test_trailing_newline_accepted(self):
        line = uart_encode({"v": 1}).decode("utf-8")
        self.assertEqual({"v": 1}, uart_decode(line))          # has \n
        self.assertEqual({"v": 1}, uart_decode(line.rstrip())) # without \n


if __name__ == "__main__":
    unittest.main()
