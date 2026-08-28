import hashlib
import re
import warnings

from astropy.utils.exceptions import AstropyWarning

# Key where the FITS hash is stored in the ASDF tree
FITS_HASH_KEY = "_fits_hash"

_builtin_regexes = [
    "",
    "NAXIS[0-9]{0,3}",
    "BITPIX",
    "XTENSION",
    "PCOUNT",
    "GCOUNT",
    "EXTEND",
    "BSCALE",
    "BZERO",
    "BLANK",
    "DATAMAX",
    "DATAMIN",
    "EXTNAME",
    "EXTVER",
    "EXTLEVEL",
    "GROUPS",
    "PYTPE[0-9]",
    "PSCAL[0-9]",
    "PZERO[0-9]",
    "SIMPLE",
    "TFIELDS",
    "TBCOL[0-9]{1,3}",
    "TDIM[0-9]{1,3}",
    "TFORM[0-9]{1,3}",
    "TTYPE[0-9]{1,3}",
    "TUNIT[0-9]{1,3}",
    "TSCAL[0-9]{1,3}",
    "TZERO[0-9]{1,3}",
    "TNULL[0-9]{1,3}",
    "TDISP[0-9]{1,3}",
    "HISTORY",
]

_builtin_regex = re.compile("|".join(f"(^{x}$)" for x in _builtin_regexes))


def fits_hash(hdulist):
    """
    Calculate a hash based on all HDU headers.

    Uses basic SHA-256 hash to calculate.

    Parameters
    ----------
    hdulist : astropy.fits.HDUList
        The FITS structure.

    Returns
    -------
    fits_hash : str
        The hash of all HDU headers.
    """
    fits_hash = hashlib.sha256()

    # Ignore FITS header warnings, such as "Card is too long".
    # Such issues are inconsequential to hash calculation.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", AstropyWarning)
        fits_hash.update("".join(str(hdu.header) for hdu in hdulist if hdu.name != "ASDF").encode())
    return fits_hash.hexdigest()


def is_builtin_fits_keyword(key):
    """
    Check if key is a FITS builtin.

    Builtins are those managed by ``astropy.io.fits``, and we don't
    want to propagate those through the `_extra_fits` mechanism.

    Parameters
    ----------
    key : str
        The keyword to check.

    Returns
    -------
    bool
        `True` if the keyword is a built-in FITS keyword.
    """
    return _builtin_regex.match(key) is not None
