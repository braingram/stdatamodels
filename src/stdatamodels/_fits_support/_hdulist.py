import warnings
from dataclasses import dataclass

from astropy.io import fits


@dataclass(slots=True)
class Card:
    keyword: str = ""
    value: str | int | float | None = ""
    comment: str = ""


class Header:
    @classmethod
    def from_astropy(cls, header):
        return cls(header.cards)

    def __init__(self, cards=None):
        self._cards = []
        self._by_keyword = {}
        if cards:
            self.extend(cards)

    def __getitem__(self, key):
        if isinstance(key, int):
            try:
                return self._cards[key]
            except IndexError as err:
                raise KeyError(f"{key} not found") from err
        return self._by_keyword[key]

    def set_card(self, card):
        try:
            existing = self[card.keyword]
            existing.value = card.value
            existing.comment = card.comment
        except KeyError:
            self.append(card)

    def __contains__(self, key):
        return key in self._by_keyword

    def keys(self):
        return self._by_keyword.keys()

    def append(self, card):
        if not isinstance(card, Card):
            card = Card(*card)
        self._cards.append(card)
        self._by_keyword[card.keyword] = card

    def extend(self, cards):
        for card in cards:
            self.append(card)

    def to_astropy(self):
        return fits.Header([(card.keyword, card.value, card.comment) for card in self._cards])


class HDU:
    @classmethod
    def from_astropy(cls, hdu):
        return cls(
            hdu.name, data=hdu.data, header=hdu.header.cards, version=hdu.header.get("EXTVER")
        )

    def __init__(self, name, *, index=None, data=None, header=None, version=None):
        self.name = name
        self.index = index
        self.data = data
        self.header = Header(header or [])
        self.version = version

    @property
    def hdu_type(self):
        if self.name.lower() == "primary":
            return fits.PrimaryHDU
        if hasattr(self.data, "dtype") and self.data.dtype.names is not None:
            return fits.BinTableHDU
        return fits.ImageHDU

    def to_astropy(self):
        hdu_type = self.hdu_type
        header = self.header.to_astropy()
        if hdu_type is fits.PrimaryHDU:
            # don't pass version or data
            return fits.PrimaryHDU(header=header)
        return hdu_type(name=self.name, data=self.data, ver=self.version, header=header)


class HDUList:
    @classmethod
    def from_astropy(cls, hdulist):
        return cls([HDU.from_astropy(hdu) for hdu in hdulist])

    def __init__(self, hdus=None):
        self._hdus = []
        # index uses lowercase names
        self._index = {}
        if hdus is None:
            hdus = [HDU("PRIMARY")]
        for hdu in hdus:
            self.append(hdu)

    def __getitem__(self, key):
        if isinstance(key, int):
            try:
                return self._hdus[key]
            except IndexError as err:
                raise KeyError("f{key} not found") from err
        if isinstance(key, str):
            name, version = key, None
        else:
            name, version = key
        lowercase_name = name.lower()
        if not self._index.get(lowercase_name):
            raise KeyError(f"Unknown HDU name {name}")
        if version is None:
            # get first
            try:
                version = next(iter(self._index[lowercase_name].keys()))
            except StopIteration:
                raise KeyError(f"Unknown HDU version {version} for {name}") from None
        return self._hdus[self._index[lowercase_name][version]]

    def __contains__(self, key):
        try:
            self[key]
        except KeyError:
            return False
        return True

    def append(self, hdu):
        hdu_index = len(self._hdus)
        name = hdu.name.lower()
        if name not in self._index:
            self._index[name] = {}

        # FIXME 1 here is to reproduce the issue on main where all created HDUS get versions
        version = hdu.version or 1
        if version not in self._index[name]:
            self._index[name][version] = hdu_index
        else:
            # warn here as we're indexing ambiguous hdus
            key = (hdu.name, hdu.version)
            msg = (
                f"Multiple HDUs share {key}, this can issues with mapping FITS to ASDF. "
                "In the future this will be an error. Assign each HDU a unique name or "
                "name/version to avoid this error"
            )
            warnings.warn(msg, UserWarning, stacklevel=2)

        self._hdus.append(hdu)

    def to_astropy(self):
        return fits.HDUList([hdu.to_astropy() for hdu in self._hdus])
