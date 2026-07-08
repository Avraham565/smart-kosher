"""Concrete adapters for local development and persistence."""

from .h2_simulator import H2Simulator
from .json_repository import JsonEventJournal, JsonRepository
from .machine_rtc import MachineRtcClock, has_rtc
from .memory_repository import MemoryEventJournal, MemoryRepository
from .settings_store import SettingsStore
from .uart_codec import decode as uart_decode
from .uart_codec import encode as uart_encode

__all__ = [
    "H2Simulator",
    "JsonEventJournal",
    "JsonRepository",
    "MachineRtcClock",
    "MemoryEventJournal",
    "MemoryRepository",
    "SettingsStore",
    "has_rtc",
    "uart_decode",
    "uart_encode",
]
