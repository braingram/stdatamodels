"""Data models for JWST."""

from ._model_base import DataModel
from . import _version


__all__ = ["DataModel", "__version__"]


__version__ = _version.version
