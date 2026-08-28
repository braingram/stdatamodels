# fits_support
# uses (internal):
# - asdf_in_fits: from_fits_asdf(hdulist, **kwargs)
# - model_base: from_fits(hdulist, schema, ctx, **kwargs)), to_fits(tree, schema)
# - jwst.datamodels.util: _load_from_schema(hdulist, schema, tree, ctx, **kwargs)
# jwst uses:
# - jwst.model_blender.blender: from_fits_hdu(table, schema)
# - jwst.residual_fringe.residual_fringe: to_fits(tree, schema)
