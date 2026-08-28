def _get_short_doc(schema):
    title = schema.get("title", None)
    description = schema.get("description", None)
    if description is None:
        description = title or ""
    else:
        if title is not None:
            description = title + "\n\n" + description
    return description.partition("\n")[0]
