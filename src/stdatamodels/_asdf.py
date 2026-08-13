from contextlib import contextmanager
from functools import cache

import asdf

# TODO the asdf-astropy extension reuses a uri for the core, will this be a problem?
# should we match by package too?
ALLOWED_EXTENSION_URIS = {
    "asdf://astropy.org/astropy/extensions/astropy-1.6.0",
    "asdf://astropy.org/astropy/extensions/astropy-1.5.0",
    "asdf://astropy.org/astropy/extensions/astropy-1.4.0",
    "asdf://astropy.org/astropy/extensions/astropy-1.3.0",
    "asdf://astropy.org/astropy/extensions/astropy-1.2.0",
    "asdf://astropy.org/astropy/extensions/astropy-1.1.0",
    "asdf://astropy.org/astropy/extensions/astropy-1.0.0",
    "asdf://asdf-format.org/astronomy/coordinates/extensions/coordinates-1.3.0",
    "asdf://asdf-format.org/astronomy/coordinates/extensions/coordinates-1.2.0",
    "asdf://asdf-format.org/astronomy/coordinates/extensions/coordinates-1.1.0",
    "asdf://asdf-format.org/astronomy/coordinates/extensions/coordinates-1.0.0",
    "asdf://asdf-format.org/transform/extensions/transform-1.7.0",
    "asdf://asdf-format.org/transform/extensions/transform-1.6.0",
    "asdf://asdf-format.org/transform/extensions/transform-1.5.0",
    "asdf://asdf-format.org/transform/extensions/transform-1.4.0",
    "asdf://asdf-format.org/transform/extensions/transform-1.3.0",
    "asdf://asdf-format.org/transform/extensions/transform-1.2.0",
    "asdf://asdf-format.org/transform/extensions/transform-1.1.0",
    "asdf://asdf-format.org/transform/extensions/transform-1.0.0",
    "asdf://astropy.org/astropy/extensions/units-1.3.0",
    "asdf://astropy.org/astropy/extensions/units-1.2.0",
    "asdf://astropy.org/astropy/extensions/units-1.1.0",
    "asdf://astropy.org/astropy/extensions/units-1.0.0",
    "asdf://asdf-format.org/astronomy/extensions/astronomy-1.2.0",
    "asdf://asdf-format.org/astronomy/extensions/astronomy-1.1.0",
    "asdf://asdf-format.org/astronomy/extensions/astronomy-1.0.0",
    "asdf://asdf-format.org/core/extensions/core-1.5.0",
    "asdf://asdf-format.org/core/extensions/core-1.4.0",
    "asdf://asdf-format.org/core/extensions/core-1.3.0",
    "asdf://asdf-format.org/core/extensions/core-1.2.0",
    "asdf://asdf-format.org/core/extensions/core-1.1.0",
    "asdf://asdf-format.org/core/extensions/core-1.0.0",
    "asdf://astropy.org/core/extensions/core-1.5.0",
    "asdf://astropy.org/core/extensions/core-1.4.0",
    "asdf://astropy.org/core/extensions/core-1.3.0",
    "asdf://astropy.org/core/extensions/core-1.2.0",
    "asdf://astropy.org/core/extensions/core-1.1.0",
    "asdf://astropy.org/core/extensions/core-1.0.0",
    "asdf://asdf-format.org/astronomy/gwcs/extensions/gwcs-1.4.0",
    "asdf://asdf-format.org/astronomy/gwcs/extensions/gwcs-1.3.0",
    "asdf://asdf-format.org/astronomy/gwcs/extensions/gwcs-1.2.0",
    "asdf://asdf-format.org/astronomy/gwcs/extensions/gwcs-1.1.0",
    "asdf://asdf-format.org/astronomy/gwcs/extensions/gwcs-1.0.1",
    "asdf://asdf-format.org/astronomy/gwcs/extensions/gwcs-1.0.0",
    "asdf://stsci.edu/jwst_pipeline/extensions/jwst_transforms-1.3.0",
    "asdf://stsci.edu/jwst_pipeline/extensions/jwst_transforms-1.2.0",
    "asdf://stsci.edu/jwst_pipeline/extensions/jwst_transforms-1.1.0",
    "asdf://stsci.edu/jwst_pipeline/extensions/jwst_transforms-1.0.0",
    "asdf://stsci.edu/jwst_pipeline/extensions/jwst_transforms-0.7.0",
    "asdf://asdf-format.org/core/extensions/core-1.6.0",
}


@cache
def get_limited_extensions():
    cfg = asdf.get_config()
    return [ext for ext in cfg.extensions if ext.extension_uri in ALLOWED_EXTENSION_URIS]


@contextmanager
def limit_extensions():
    with asdf.config_context() as cfg:
        # limit extensions
        cfg._extensions = get_limited_extensions()
        yield cfg
