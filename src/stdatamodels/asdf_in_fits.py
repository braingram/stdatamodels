import asdf
import numpy as np
from astropy.io import fits

from stdatamodels import fits_support
from stdatamodels._fits_support._asdf import (
    _ASDF_EXTENSION_NAME,
    _create_asdf_hdu,
    _create_tagged_dict_for_fits_array,
)

__all__ = ["open", "to_hdulist", "write"]

# This API is intended to replace the removed asdf.AsdfInFits
# for community (non-pipeline) usage. When considering changes
# a wider search for usage beyond pipeline code and documentation
# is recommended as well as longer deprecation periods that
# aren't as closely linked to pipeline releases.


def to_hdulist(tree, hdulist=None):
    """
    Add ASDF data to an hdulist (or create one if needed).

    Parameters
    ----------
    tree : ASDF tree or dict
        ASDF data to add to the hdulist

    hdulist : `astropy.io.fits.HDUList`
        Optional HDUList to add the ASDF data to. If not provided,
        a new HDUList will be created.

    Returns
    -------
    `astropy.io.fits.HDUList` :
        HDUList with added ASDF data.
    """
    if hdulist is None:
        hdulist = fits.HDUList([fits.PrimaryHDU()])
    else:
        hdu_data_ids = {
            id(hdu.data): (i, hdu) for i, hdu in enumerate(hdulist) if hdu.data is not None
        }

        def callback(node):
            if (
                isinstance(node, (np.ndarray, asdf.tags.core.NDArrayType))
                and id(node) in hdu_data_ids
            ):
                hdu_index, hdu = hdu_data_ids[id(node)]
                return _create_tagged_dict_for_fits_array(hdu, hdu_index)
            return node

        tree = asdf.treeutil.walk_and_modify(tree, callback)

    # add the asdf extension
    if _ASDF_EXTENSION_NAME in hdulist:
        del hdulist[_ASDF_EXTENSION_NAME]

    hdulist.append(_create_asdf_hdu(tree))
    return hdulist


def write(filename, tree, hdulist=None, **kwargs):
    """
    Write ASDF data inside a FITS file.

    Parameters
    ----------
    filename : str or path
        Filename where the resulting fits file containing the ASDF
        data will be saved. This is passed on to
        :meth:`astropy.io.fits.HDUList.writeto`
    tree : ASDF tree or dict
        ASDF data to save in the fits file
    hdulist : `astropy.io.fits.HDUList`
        Optional HDUList to write the ASDF data to. If not provided,
        a new HDUList will be created.
    **kwargs
        Additional keyword arguments to pass to :meth:`astropy.io.fits.HDUList.writeto`
    """
    to_hdulist(tree, hdulist=hdulist).writeto(filename, **kwargs)


def open(filename_or_hdu, ignore_missing_extensions=False, ignore_unrecognized_tag=False):  # noqa: A001
    """
    Read ASDF data embedded in a fits file.

    Parameters
    ----------
    filename_or_hdu : str, path, `astropy.io.fits.HDUList`
        Filename of the FITS file or an open `astropy.io.fits.HDUList`
        containing the ASDF data. If a filename is provided it
        will be opened with :func:`astropy.io.fits.open`.
    ignore_missing_extensions : bool, optional
        If `True`, ignore missing extensions in the FITS file.
        Defaults to `False`.
    ignore_unrecognized_tag : bool, optional
        If `True`, ignore unrecognized tags in the ASDF data.
        Defaults to `False`.

    Returns
    -------
    af : :obj:`asdf.AsdfFile`
        :obj:`asdf.AsdfFile` created from ASDF data embedded in the opened
        FITS file.
    """
    is_hdu = isinstance(filename_or_hdu, fits.HDUList)
    hdulist = filename_or_hdu if is_hdu else fits.open(filename_or_hdu)
    af = fits_support.from_fits_asdf(
        hdulist,
        ignore_missing_extensions=ignore_missing_extensions,
        ignore_unrecognized_tag=ignore_unrecognized_tag,
    )

    if is_hdu:
        # no need to wrap close if input was an HDUList
        return af

    # on close, close hdulist
    def wrap_close(af, hdulist):
        def close():
            asdf.AsdfFile.close(af)
            hdulist.close()

        return close

    af.close = wrap_close(af, hdulist)
    return af
