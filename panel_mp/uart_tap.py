"""Passive wire log for the H2 link, for confirming what a command really does.

The H2 sits on UART1 *inside* the panel, so there is no wire to clip a second
adapter onto: the only place the conversation is visible is the process that
owns the port. This wraps the two funnels every frame already passes through --
``_write_cmd`` outbound (``_command`` calls it too, so one wrapper catches both
the awaited and the fire-and-forget senders) and ``process_line`` inbound -- and
prints each one to the USB console.

Strictly an observer: it forwards every call unchanged, sends nothing of its
own, and never touches the registry. Safe to leave installed; off by default
only because it shares the console the hardware tests scrape.

    # on the panel
    import uart_tap; uart_tap.install(gateway)

    # or, from the host, without editing anything:
    python -m mpremote connect COM8 touch :data/uart_tap   # then reset

main.py calls maybe_install() at boot, so creating /data/uart_tap turns the log
on for the next boot and deleting it turns it off.
"""

try:
    from time import ticks_ms
except ImportError:                       # CPython, for the desktop tests
    from time import monotonic

    def ticks_ms():
        return int(monotonic() * 1000)

_PREFIX = "[h2]"


def install(gateway, log=print):
    """Wrap the gateway's inbound and outbound funnels. Returns the gateway."""
    if getattr(gateway, "_tapped", False):
        return gateway                    # a second install would double-print
    write_cmd = gateway._write_cmd
    process_line = gateway.process_line

    def tapped_write_cmd(op, payload, rid=None):
        rid = write_cmd(op, payload, rid)
        log(_PREFIX, ticks_ms(), "TX", op, rid, payload)
        return rid

    def tapped_process_line(line):
        # Printed raw and before dispatch, so a frame that process_line rejects
        # as undecodable -- or one that makes it raise -- is still on the log.
        try:
            text = bytes(line).strip().decode()
        except Exception:
            text = repr(line)
        log(_PREFIX, ticks_ms(), "RX", text)
        return process_line(line)

    gateway._write_cmd = tapped_write_cmd
    gateway.process_line = tapped_process_line
    gateway._tapped = True
    log(_PREFIX, "wire log on - every H2 frame will be printed")
    return gateway


def maybe_install(gateway, flag_path, log=print):
    """Install only if the flag file exists, so a bench session is opt-in."""
    try:
        open(flag_path).close()
    except OSError:
        return gateway
    return install(gateway, log)
