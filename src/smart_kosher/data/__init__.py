"""Packaged configuration data and validated loaders."""

from .cities import CityDataError, get_city, load_cities

__all__ = ["CityDataError", "get_city", "load_cities"]
