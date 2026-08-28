from collections import deque
from dataclasses import dataclass
from enum import Enum, unique

from astropy.io import fits

from stdatamodels._fits_support._schema import _get_short_doc
from stdatamodels.schema import walk_schema

DEFAULT_HDU_ORDER = ["PRIMARY", "SCI", "DQ", "ERR"]


@unique
class MappingType(Enum):
    ARRAY = 0
    KEYWORD = 1


@dataclass(slots=True)
class MappingEntry:
    name: str
    mapping_type: MappingType
    path: list[str]
    subschema: dict


def _set_tree(tree, path, value):
    node = tree
    for subpath in path[:-1]:
        if subpath not in node:
            node[subpath] = {}
        node = node[subpath]
    node[path[-1]] = value


def _set_tree_data(tree, path, data_by_ver):
    # This assumes only 1 "items" path component. There is a unit
    # test to confirm that fits mappings are only ever 1 "items" deep.
    # shortcut non-items paths
    if "items" not in path:
        return _set_tree(tree, path, data_by_ver.popitem()[-1])
    items_index = path.index("items")
    *base, list_key = path[:items_index]
    item_keys = path[items_index + 1 :]

    # first find the list
    node = tree
    for key in base:
        if key not in node:
            node[key] = {}
        node = node[key]

    # make list
    max_length = max(data_by_ver.keys())
    if list_key not in node:
        node[list_key] = [{}] * max_length
    elif len(node[list_key]) < max_length:
        node[list_key].extend([{}] * (max_length - len(node[list_key])))

    for ver, data in data_by_ver.items():
        # ver here is 1-based so subtract 1 for the node index
        _set_tree_data(node[list_key][ver - 1], item_keys, {ver: data})


def _entries_to_graph(index):
    graph = {}
    for entry in index:
        node = graph
        *edges, leaf = entry.path
        for edge in edges:
            if edge not in node:
                node[edge] = {}
            elif not isinstance(node[edge], dict):
                raise ValueError(f"Expected edge at {edge} found {type(node[edge])}")
            node = node[edge]
        if leaf in node:
            raise ValueError(f"Multiple entries for {leaf}: {node[leaf]}, {entry}")
        node[leaf] = entry
    return graph


@dataclass(slots=True)
class FITSASDFMapping:
    entries: list[MappingEntry]
    graph: dict
    section_titles: dict

    @classmethod
    def from_schema(cls, schema, *, expected_hdu_order=None):
        expected_hdu_order = [name.upper() for name in (expected_hdu_order or DEFAULT_HDU_ORDER)]

        # track section titles for later writing as FITS comments
        section_titles = {}

        def callback(subschema, path, combiner, entries, recurse):
            if not isinstance(subschema, dict):
                return

            if "properties" in subschema and "title" in subschema:
                # capture header comments, these are "title" entries of parent
                # schemas for subschemas that contain "fits_keyword" entries
                section_titles[".".join(path)] = subschema["title"]

            if not ("fits_hdu" in subschema or "fits_keyword" in subschema):
                return

            # default to PRIMARY
            fits_hdu = subschema.get("fits_hdu", "PRIMARY")
            mapping_type = MappingType.KEYWORD if "fits_keyword" in subschema else MappingType.ARRAY
            entries.append(MappingEntry(fits_hdu, mapping_type, path, subschema))

        entries = []
        walk_schema(schema, callback, entries)

        # order the entries so that:
        # - hdus appear in expected order
        # - keyword entries for an hdu occur after any array entry

        def index_sort(entry):
            # start key with fits_hdu
            fits_hdu = entry.name.upper()

            # if this is an ordered hdu use the index of the name
            if fits_hdu in expected_hdu_order:
                key = f"{expected_hdu_order.index(fits_hdu):010d}"
            else:
                key = fits_hdu

            # next, either use the path or 0 (for arrays) or 1 (for keywords)
            # to order array assignments first and keywords second (with each
            # keyword in the order they were found above)
            if entry.mapping_type == MappingType.ARRAY:
                return f"{key}_0"
            return f"{key}_1"

        entries.sort(key=index_sort)
        graph = _entries_to_graph(entries)
        return cls(entries, graph, section_titles)

    def to_hdulist(self, model, extra):
        per_hdu_section_titles = {}

        hdus = {("PRIMARY", 1): fits.PrimaryHDU()}
        headers = {}
        queue = deque([(model.instance, self.graph, 1)])
        while queue:
            node, item, ver = queue.popleft()
            if isinstance(item, dict):  # populate queue
                if isinstance(node, dict):
                    for k, v in item.items():
                        if k not in node:  # nothing to do
                            continue
                        queue.append((node[k], v, ver))
                else:
                    assert isinstance(node, list)
                    assert len(item) == 1 and "items" in item
                    subitem = item["items"]
                    for i, subnode in enumerate(node):
                        queue.append((subnode, subitem, i + 1))
            else:
                # process entry/item

                # array
                if item.mapping_type == MappingType.ARRAY:
                    hdu_type = fits.BinTableHDU if node.dtype.fields else fits.ImageHDU
                    hdu = hdu_type(name=item.name, data=node, ver=ver)
                    hdus[(hdu.name, hdu.ver)] = hdu
                    continue

                # keyword, queue them for later
                header_key = (item.name, ver)
                if header_key not in headers:
                    headers[header_key] = []

                # check for all section headers
                # Do this per-hdu.name instead of per-file
                # that way multiple SCI extensions that list coordinate information will
                # all have section headers.
                # Search for parent titles as well
                # eg: meta.ref_file defines a title used by meta.ref_file.foo.name
                # TODO perhaps there is a more efficient way to store these?
                if header_key not in per_hdu_section_titles:
                    per_hdu_section_titles[header_key] = self.section_titles.copy()
                section_titles = per_hdu_section_titles[header_key]
                for i in range(1, len(item.path) - 1):
                    section_key = ".".join(item.path[:i])
                    if section_title := section_titles.pop(section_key, None):
                        headers[header_key].extend(
                            [
                                (" ", ""),
                                (" ", section_title),
                                (" ", ""),
                            ]
                        )

                # check for a header comment
                headers[header_key].append(
                    (
                        item.subschema["fits_keyword"],
                        node,
                        _get_short_doc(item.subschema),
                    )
                )

        # now map extra.... TODO should this be outside?
        for hdu_name, hdu_info in extra.items():
            # hdu_info = {"data": ..., "header": [(k, v, comment)]}
            if "data" in hdu_info:
                data = hdu_info["data"]
                # FIXME case NOT handled here
                hdus[(hdu_name, 1)]
                hdu_type = fits.BinTableHDU if data.dtype.fields else fits.ImageHDU
                # FIXME is 1 always right here?
                hdu = hdu_type(name=hdu_name, data=data, ver=1)
                hdus[(hdu_name, 1)] = hdu
            if "header" in hdu_info:
                # FIXME case NOT handled here
                header_key = (hdu_name, 1)
                if header_key not in headers:
                    headers[header_key] = []
                headers[header_key].extend(hdu_info["header"])

        # apply headers
        for key in headers:
            if key in hdus:
                hdu = hdus[key]
            else:
                hdu = fits.ImageHDU(name=key[0], ver=key[1])
                hdus[key] = hdu
            # end is needed here or else astropy reorders things and takes significantly longer
            hdu.header.extend(headers[key], end=True)

        return fits.HDUList(list(hdus.values()))

    def from_hdulist(self, hdulist, tree=None):
        tree = tree or {}
        # pre-index hdulist and headers
        # this also gets returned to track what was not mapped
        hdus = {}
        for hdu in hdulist:
            name = hdu.name.upper()
            if name not in hdus:
                hdus[name] = {}
            ver = hdu.ver
            assert ver not in hdus[name]
            hdus[name][ver] = {
                "data": hdu.data,
                # FIXME this loses comments
                "header": {
                    card.keyword.upper(): (card.value, card.comment) for card in hdu.header.cards
                },
            }

        for entry in self.entries:
            name = entry.name.upper()

            if name not in hdus:
                continue

            matching_hdus = hdus[name]

            if entry.mapping_type == MappingType.ARRAY:
                # pop data for these hdus
                data = {}
                for ver, hdu in matching_hdus.items():
                    if hdu["data"] is not None:
                        data[ver] = hdu["data"]
                        # set data to None to mark it as mapped
                        hdu["data"] = None
                _set_tree_data(tree, entry.path, data)
                continue

            # keyword
            keyword = entry.subschema["fits_keyword"].upper()
            values_by_ver = {}
            for ver, hdu in matching_hdus.items():
                if keyword in hdu["header"]:
                    values_by_ver[ver] = hdu["header"].pop(keyword)[0]
            if not values_by_ver:
                # nothing to set
                continue
            _set_tree_data(tree, entry.path, values_by_ver)
        # FIXME extra isn't in quite the same format
        # headers are key: (value, comment) not (key, value, comment)
        return tree, hdus
