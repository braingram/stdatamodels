import io

import asdf
import numpy as np
from asdf import tagged
from asdf.tags.core import ndarray
from astropy.io import fits

from stdatamodels import util

_ASDF_EXTENSION_NAME = "ASDF"
_FITS_SOURCE_PREFIX = "fits:"
if asdf.versioning.default_version > "1.5.0":
    _NDARRAY_TAG = "tag:stsci.edu:asdf/core/ndarray-1.1.0"
else:
    _NDARRAY_TAG = "tag:stsci.edu:asdf/core/ndarray-1.0.0"


def _create_asdf_hdu(tree, schema=None):
    buffer = io.BytesIO()
    # convert all FITS_rec instances to numpy arrays, this is needed as
    # some arrays loaded from the FITS data for old files may not be defined
    # in the current schemas. These will be loaded as FITS_rec instances but
    # not linked back (and safely converted) on write if they are removed
    # from the schema.
    af = asdf.AsdfFile(util.convert_fitsrec_to_array_in_tree(tree))
    if schema:
        tt = asdf.yamlutil.custom_tree_to_tagged_tree(af.tree, af)
        validators = asdf.schema.YAML_VALIDATORS
        asdf.schema.validate(tt, af, schema, validators)
    af.write_to(buffer)
    # asdf.AsdfFile(util.convert_fitsrec_to_array_in_tree(tree)).write_to(buffer)
    buffer.seek(0)

    data = np.array(buffer.getbuffer(), dtype=np.uint8)[None, :]
    fmt = f"{len(data[0])}B"
    column = fits.Column(array=data, format=fmt, name="ASDF_METADATA")
    return fits.BinTableHDU.from_columns([column], name=_ASDF_EXTENSION_NAME)


def _create_tagged_dict_for_fits_array(hdu, hdu_index):
    # Views over arrays stored in FITS files have some idiosyncrasies.
    # astropy.io.fits always writes arrays C-contiguous with big-endian
    # byte order, whereas asdf preserves the "contiguousity" and byte order
    # of the base array.
    dtype, byteorder = ndarray.numpy_dtype_to_asdf_datatype(
        hdu.data.dtype, include_byteorder=True, override_byteorder="big"
    )

    if hdu.name == "":
        source = f"{_FITS_SOURCE_PREFIX}{hdu_index}"
    else:
        source = f"{_FITS_SOURCE_PREFIX}{hdu.name},{hdu.ver}"

    return tagged.TaggedDict(
        data={
            "source": source,
            "shape": list(hdu.data.shape),
            "datatype": dtype,
            "byteorder": byteorder,
        },
        tag=_NDARRAY_TAG,
    )


def _link_fits_array(hdu):
    # Views over arrays stored in FITS files have some idiosyncrasies.
    # astropy.io.fits always writes arrays C-contiguous with big-endian
    # byte order, whereas asdf preserves the "contiguousity" and byte order
    # of the base array.
    dtype, byteorder = ndarray.numpy_dtype_to_asdf_datatype(
        hdu.data.dtype, include_byteorder=True, override_byteorder="big"
    )

    return tagged.TaggedDict(
        data={
            "source": f"{_FITS_SOURCE_PREFIX}{hdu.name},{hdu.version}",
            "shape": list(hdu.data.shape),
            "datatype": dtype,
            "byteorder": byteorder,
        },
        tag=_NDARRAY_TAG,
    )
