"""WiFi Access Point setup for the headless hub (SmartKosher network)."""

SSID = "SmartKosher"

try:
    import network as _network
    _HAS_NETWORK = True
except ImportError:
    _HAS_NETWORK = False


def start():
    if not _HAS_NETWORK:
        return {"ssid": SSID, "ip": "127.0.0.1", "mode": "dev"}
    ap = _network.WLAN(_network.AP_IF)
    ap.active(True)
    ap.config(essid=SSID, authmode=_network.AUTH_OPEN)
    while not ap.active():
        pass
    ip = ap.ifconfig()[0]
    return {"ssid": SSID, "ip": ip, "mode": "ap"}
