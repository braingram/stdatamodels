import datetime
from collections import deque
from dataclasses import dataclass
from enum import Enum, unique

import astropy.time

from stdatamodels._fits_support._asdf import _link_fits_array
from stdatamodels._fits_support._fits import HDU, Card, FITSFile
from stdatamodels._fits_support._schema import _get_short_doc
from stdatamodels.schema import walk_schema
from stdatamodels.validate import _validate_datatype

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

        # track entries already seen
        seen = set()

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
            seen_key = (fits_hdu, mapping_type, ".".join(path))
            if seen_key in seen:
                return
            seen.add(seen_key)
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

    def to_fitsfile(self, tree, fitsfile=None):
        per_hdu_section_titles = {}

        if fitsfile is None:
            fitsfile = FITSFile()

        # queue items = (tree, subgraph, version, parent, child_key)
        queue = deque([(tree, self.graph, 1, None, None)])

        while queue:
            node, item, ver, parent, child_key = queue.popleft()
            if isinstance(item, dict):  # subgraph, populate queue
                if isinstance(node, dict):
                    for k, v in item.items():
                        if k not in node:
                            continue
                        queue.append((node[k], v, ver, node, k))
                else:
                    subitem = item["items"]
                    for i, subnode in enumerate(node):
                        queue.append((subnode, subitem, i + 1, node, i))
            else:
                key = (item.name, ver)
                if key in fitsfile:
                    hdu = fitsfile[key]
                else:
                    hdu = HDU(item.name, version=ver)
                    fitsfile.append(hdu)

                # process item
                if item.mapping_type == MappingType.ARRAY:
                    # validate datatype here since we lie to asdf
                    if "datatype" in item.subschema:
                        for error in _validate_datatype(
                            None, item.subschema["datatype"], node, item.subschema
                        ):
                            raise error
                    # record the mapping of node to data here
                    hdu.data = node
                    parent[child_key] = _link_fits_array(hdu, item.subschema)
                    continue

                # keyword
                keyword = item.subschema["fits_keyword"]
                if keyword in hdu.header:
                    continue

                # first add section headers
                # check for all section headers
                # Do this per-hdu.name instead of per-file
                # that way multiple SCI extensions that list coordinate information will
                # all have section headers.
                # Search for parent titles as well
                # eg: meta.ref_file defines a title used by meta.ref_file.foo.name
                # TODO perhaps there is a more efficient way to store these?
                if key not in per_hdu_section_titles:
                    per_hdu_section_titles[key] = self.section_titles.copy()
                section_titles = per_hdu_section_titles[key]
                for i in range(1, len(item.path)):
                    section_key = ".".join(item.path[:i])
                    if section_title := section_titles.pop(section_key, None):
                        hdu.header.append(Card(" "))
                        hdu.header.append(Card(" ", section_title))
                        hdu.header.append(Card(" "))

                if isinstance(node, datetime.datetime):
                    node = astropy.time.Time(node)
                if isinstance(node, astropy.time.Time):
                    node = str(astropy.time.Time(node, format="iso"))
                # then add keycard
                hdu.header.append(Card(keyword, node, _get_short_doc(item.subschema)))
        return fitsfile

    def to_hdulist(self, tree, extra=None):
        extra = {} or extra
        fitsfile = self.to_fitsfile(tree)
        for name, data in extra.items():
            if name not in fitsfile:
                hdu = HDU(name)
                fitsfile.append(hdu)
            else:
                hdu = fitsfile[name]
            if "data" in data:
                hdu.data = data["data"]
            if "header" in data:
                for card_data in data["header"]:
                    hdu.header.set_card(Card(*card_data))
        return fitsfile.to_astropy()

    def from_fitsfile(self, fitsfile, tree=None):
        tree = tree or {}
        seen_data = set()
        seen_keywords = {}

        for entry in self.entries:
            if entry.name not in fitsfile:
                continue

            if entry.mapping_type == MappingType.ARRAY:
                seen_data.add(entry.name)
                _set_tree_data(tree, entry.path, fitsfile.by_version(entry.name))
                continue

            # keyword
            keyword = entry.subschema["fits_keyword"]
            values_by_ver = {
                ver: hdu.header[keyword]
                for ver, hdu in fitsfile.by_version(entry.name).items()
                if keyword in hdu.header
            }
            if not values_by_ver:
                continue
            if entry.name not in seen_keywords:
                seen_keywords[entry.name] = {}
            for ver in values_by_ver.keys():
                seen_keywords[entry.name][ver] = keyword
            _set_tree_data(tree, entry.path, values_by_ver)

        return tree, seen_data, seen_keywords

    def from_hdulist(self, hdulist, tree=None):
        fitsfile = FITSFile.from_astropy(hdulist)
        return self.from_fitsfile(fitsfile, tree)
