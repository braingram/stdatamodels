# fits_support
# uses (internal):
# - asdf_in_fits: from_fits_asdf(hdulist, **kwargs)
# - model_base: from_fits(hdulist, schema, ctx, **kwargs)), to_fits(tree, schema)
# - jwst.datamodels.util: _load_from_schema(hdulist, schema, tree, ctx, **kwargs)
# jwst uses:
# - jwst.model_blender.blender: from_fits_hdu(table, schema)
# - jwst.residual_fringe.residual_fringe: to_fits(tree, schema)
#
# jwst uses may take a bit to untangle
# - from_fits_hdu: this should be handled automatically...
# - to_fits: I don't see a reasonable replacement for this, it's essentially generating a
#            primary HDU for the input model type, throwing away the rest of that model
#            then adding it's own HDUs.
