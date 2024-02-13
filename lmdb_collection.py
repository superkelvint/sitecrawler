import json
from typing import Optional, Any

import lmdb
from lmdbm import Lmdb

_binary_suffix = "^bytes"


class JsonLmdb(Lmdb):
    """
    Serializes and deserializes values to/from lmdb using JSON.
    If the key has a binary suffix (hardcoded as ^bytes), then the JSON ser/deserialization is skipped.
    """
    def _pre_key(self, value):
        return value.encode("utf-8")

    def _post_key(self, value):
        return value.decode("utf-8")

    def _pre_value(self, value):
        return json.dumps(value).encode("utf-8")

    def _post_value(self, value):
        return json.loads(value.decode("utf-8"))

    def __getitem__(self, key):
        """
        This was copied wholesale from parent class, with the exception of checking for
        "if not key.endswith(_binary_suffix):" before calling _post_value
        """
        # type: (KT, ) -> VT

        with self.env.begin() as txn:
            value = txn.get(self._pre_key(key))
        if value is None:
            raise KeyError(key)
        if not key.endswith(_binary_suffix):
            value = self._post_value(value)
        return value

    def __setitem__(self, key, value):
        """
        This was copied wholesale from parent class, with the exception of checking for
        "if not key.endswith(_binary_suffix):" before calling _pre_value(value)
        """
        # type: (KT, VT) -> None

        k = self._pre_key(key)
        if not key.endswith(_binary_suffix):
            v = self._pre_value(value)
        else:
            v = value
        for i in range(12):
            try:
                with self.env.begin(write=True) as txn:
                    txn.put(k, v)
                    return
            except lmdb.MapFullError:
                if not self.autogrow:
                    raise
                new_map_size = self.map_size * 2
                self.map_size = new_map_size

        exit(self.autogrow_error.format(self.env.path()))

    def items(self):
        """
        This was copied wholesale from parent class, with the exception of checking for
        "if not key.endswith(_binary_suffix):" before calling _post_value(value)
        """
        # type: () -> Iterator[Tuple[KT, VT]]

        with self.env.begin() as txn:
            for key, value in txn.cursor().iternext(keys=True, values=True):
                key = self._post_key(key)
                if not key.endswith(_binary_suffix):
                    value = self._post_value(value)
                yield (key, value)


class LmdbmDocumentCollection:

    def __init__(self, file: str, mode: str = "c") -> None:
        super().__init__()
        self.file = file
        self.db = JsonLmdb.open(file, mode, map_size=2 ** 30)

    def add(self, key: str, content: Optional[str], **kwargs) -> None:
        if content is not None:
            kwargs["_content"] = content
        self.db[key] = kwargs

    def add_html(self, key: str, content: str, **kwargs) -> None:
        kwargs["_content"] = content
        kwargs["content_type"] = "text/html"
        self.db[key] = kwargs

    def add_binary(self, key: str, content: bytes, content_type: str, **kwargs) -> None:
        # binary files get their bytes saved to _bytes and in the extraction phase, the _content field gets populated
        kwargs["_content"] = "N/A"
        kwargs["content_type"] = content_type
        self.db[key] = kwargs
        self.db[key + _binary_suffix] = content

    def add_text(self, key: str, content: str, **kwargs) -> None:
        kwargs["_content"] = content
        kwargs["content_type"] = "text/plain"
        self.db[key] = kwargs

    def get_content(self, key: str):
        return self.db[key]["_content"]

    def get_binary(self, key: str):
        return self.db[key + _binary_suffix]

    def set_property(self, key: str, property_name: str, property_value: Any) -> None:
        val = self.db[key]
        val[property_name] = property_value
        self.db[key] = val

    def __getitem__(self, key):
        return self.db.__getitem__(key)

    def __setitem__(self, key, value):
        self.db.__setitem__(key, value)

    def __delitem__(self, key):
        self.db.__delitem__(key)

    def __contains__(self, key):
        return self.db.__contains__(key)

    def clear(self):
        self.db.clear()

    def keys(self):
        return self.db.keys()

    def items(self):
        return self.db.items()

    def is_binary_key(self, key):
        return key.endswith("^bytes")

    def filter_keys(self, key, value):
        for k, v in self.db.items():
            if self.is_binary_key(k):
                continue
            if v[key] == value:
                yield k

    def filter_values(self, key, value):
        for k, v in self.db.items():
            if self.is_binary_key(k):
                continue
            if v[key] == value:
                yield v

    def filter_items(self, key, value):
        for k, v in self.db.items():
            if self.is_binary_key(k):
                continue
            if v[key] == value:
                yield k, v

    def __iter__(self):
        return self.db.__iter__()

    def __len__(self):
        return self.db.__len__()

    def close(self):
        self.db.close()
