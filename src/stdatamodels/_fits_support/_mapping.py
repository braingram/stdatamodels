from collections import deque
from dataclasses import dataclass
from enum import Enum, unique

from astropy.io import fits

from stdatamodels import fits_support
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


# TODO these assume no nested items (which I think is a safe assumption)
# TODO this also assumes equal contents (all slits have "data")
def _set_tree_data(tree, path, data_by_ver):
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
    if list_key not in node:
        # FIXME this assumes all per-version data is of consistent length
        node[list_key] = [{}] * max(data_by_ver.keys())

    for i, subnode in enumerate(node[list_key]):
        ver = i + 1
        if ver not in data_by_ver:
            continue
        _set_tree_data(subnode, item_keys, {ver: data_by_ver[ver]})


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

        # order the entriesso that:
        # - hdus appear in expected order TODO TBD order needs to be determined
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

    def to_hdulist(self, model):
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
                # all have section headers
                # TODO avoid the while here, it's needed to catch nested section header comments
                # eg: meta.ref_file defines a title used by meta.ref_file.foo.name
                if header_key not in per_hdu_section_titles:
                    per_hdu_section_titles[header_key] = self.section_titles.copy()
                section_titles = per_hdu_section_titles[header_key]
                clip = -1
                while section_key := ".".join(item.path[:clip]):
                    if section_title := section_titles.pop(section_key, None):
                        headers[header_key].extend(
                            [
                                (" ", ""),
                                (" ", section_title),
                                (" ", ""),
                            ]
                        )
                    clip -= 1

                # check for a header comment
                headers[header_key].append(
                    (
                        item.subschema["fits_keyword"],
                        node,
                        fits_support._get_short_doc(item.subschema),
                    )
                )

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
        hdus = {}
        for hdu in hdulist:
            name = hdu.name.upper()
            if name not in hdus:
                hdus[name] = {}
            ver = hdu.ver
            assert ver not in hdus[name]
            hdus[name][ver] = {
                "data": hdu.data,
                "header": {card.keyword.upper(): card.value for card in hdu.header.cards},
            }

        # TODO is it better to use the graph or entries here?

        for entry in self.entries:
            name = entry.name.upper()

            if name not in hdus:
                continue

            matching_hdus = hdus[name]

            if entry.mapping_type == MappingType.ARRAY:
                _set_tree_data(tree, entry.path, {k: v["data"] for k, v in matching_hdus.items()})
                continue

            # keyword
            keyword = entry.subschema["fits_keyword"].upper()
            values_by_ver = {}
            for ver, hdu in matching_hdus.items():
                if keyword in hdu["header"]:
                    values_by_ver[ver] = hdu["header"][keyword]
            if not values_by_ver:
                # nothing to set
                continue
            _set_tree_data(tree, entry.path, values_by_ver)
        return tree
