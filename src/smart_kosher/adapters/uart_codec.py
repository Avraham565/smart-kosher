"""UART line codec: '<crc32hex> <json>\\n' envelope (docs/UART_PROTOCOL.md)."""

import binascii
import json as _json

_LOWER_HEX = "0123456789abcdef"


def encode(msg):
    """Serialize msg to a UART line.  Key order follows insertion order of msg.

    The CRC covers the sender's own serialization, so the exact separator
    style does not affect interop — but MicroPython's json.dumps rejects
    the kwargs CPython uses (TypeError: extra keyword arguments given),
    hence the fallback. ASCII escaping (the default) is fine either way:
    protocol payloads are ASCII.
    """
    try:
        body = _json.dumps(msg, separators=(",", ":"))
    except TypeError:  # MicroPython
        body = _json.dumps(msg)
    crc = binascii.crc32(body.encode("utf-8")) & 0xFFFFFFFF
    return "{:08x} {}\n".format(crc, body).encode("utf-8")


def decode(line):
    """Parse and CRC-validate one UART line.  Raises ValueError on mismatch."""
    if isinstance(line, (bytes, bytearray)):
        line = line.decode("utf-8")
    line = line.rstrip("\n\r")
    parts = line.split(" ", 1)
    if len(parts) != 2:
        raise ValueError("bad_crc: missing space delimiter")
    crc_hex, body = parts
    if len(crc_hex) != 8 or any(ch not in _LOWER_HEX for ch in crc_hex):
        raise ValueError("bad_crc: non-hex prefix {!r}".format(crc_hex))
    expected = int(crc_hex, 16)
    actual = binascii.crc32(body.encode("utf-8")) & 0xFFFFFFFF
    if expected != actual:
        raise ValueError("bad_crc: expected {} got {:08x}".format(crc_hex, actual))
    return _json.loads(body)
