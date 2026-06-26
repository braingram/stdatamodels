"""Data models for JWST."""

from . import _version
from .model_base import DataModel

__all__ = ["DataModel", "__version__"]


__version__ = _version.version


# patch FITS_rec to be case sensitive

import astropy.io.fits


def _get_index(names, key):
    """
    Get the index of the ``key`` in the ``names`` list.

    The ``key`` can be an integer or string.  If integer, it is the index
    in the list.  If string,

        a. Field (column) names are case sensitive: you can have two
           different columns called 'abc' and 'ABC' respectively.

        b. When you *refer* to a field (presumably with the field
           method), it will try to match the exact name first, so in
           the example in (a), field('abc') will get the first field,
           and field('ABC') will get the second field.

        If there is no exact name matched, it will try to match the
        name with case insensitivity.  So, in the last example,
        field('Abc') will cause an exception since there is no unique
        mapping.  If there is a field named "XYZ" and no other field
        name is a case variant of "XYZ", then field('xyz'),
        field('Xyz'), etc. will get this field.
    """
    if astropy.io.fits.column._is_int(key):
        return int(key)
    if not isinstance(key, str):
        raise KeyError(f"Illegal key '{key!r}'.")
    try:  # try to find exact match first
        return names.index(key.rstrip())
    except ValueError:  # try to match case-insentively,
        raise KeyError(f"Key '{key}' does not exist.")


astropy.io.fits.column._get_index = _get_index
