"""Minimal pure-Python HDF5 reader for SHMÚ ODIM_H5 radar composites.

This is **not** a general HDF5/ODIM library. It reads exactly the structure
SHMÚ's ``weather/radar/composite/skcomp`` files use, verified against live
data on 2026-05-17 across all four products (issue #6 spike):

* HDF5 **superblock version 0**, 8-byte offsets/lengths, classic group
  structure (symbol-table B-tree + local heap), **version-1 object headers**;
* one composite dataset ``/dataset1/data1/data`` stored as a **single
  deflate-compressed chunk** spanning the whole array — ``u8`` for the
  reflectivity / echo-top products, little-endian ``f32`` for the precip
  accumulation product;
* the ODIM ``/what /where`` and ``/dataset1/what`` attribute groups.

Anything outside that subset raises :class:`ShmuDataError` *loudly* rather
than silently mis-decoding (same contract as :mod:`shmu_opendata.grib2`): the
server has no API, so an upstream format change must fail visibly, not corrupt
a radar image. Only the Python standard library is used (``struct`` + the
stdlib ``zlib`` for the deflate filter) so the vendored library stays
HA-free, pure-Python and offline-testable.

Reference: HDF5 File Format Specification (v0 superblock, v1 object header);
EUMETNET OPERA ODIM_H5 2.1 information model.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .exceptions import ShmuDataError

# --- HDF5 message type numbers (only the ones these files use) ---------------
_MSG_NIL = 0x00
_MSG_DATASPACE = 0x01
_MSG_DATATYPE = 0x03
_MSG_DATA_LAYOUT = 0x08
_MSG_FILTER_PIPELINE = 0x0B
_MSG_ATTRIBUTE = 0x0C
_MSG_CONTINUATION = 0x10
_MSG_SYMBOL_TABLE = 0x11

_OBJECT_HEADER_V1_PREFIX = 16  # 12-byte prefix + 4 bytes padding
_DEFLATE_FILTER_ID = 1
_MAX_GROUP_DEPTH = 8  # these files nest 3 levels; this is a safety bound

#: ODIM attribute values we surface (everything else in the file is ignored).
AttrValue = str | float | int


def _u(data: bytes, offset: int, length: int) -> int:
    """Read a little-endian unsigned integer (HDF5 metadata byte order)."""
    return int.from_bytes(data[offset : offset + length], "little")


@dataclass(frozen=True, slots=True)
class OdimComposite:
    """A decoded ODIM_H5 single-quantity radar composite.

    ``raw`` holds the decompressed pixel buffer in row-major order with row 0
    at the **north** edge (ODIM convention); ``dtype`` says how to read it
    (``"u8"`` one byte per pixel, ``"f32"`` little-endian 32-bit float). The
    physical value of a pixel is ``offset + gain * stored`` with ``nodata`` /
    ``undetect`` flagging "never radiated" / "no echo" — interpreting that
    into a picture is the caller's job (see :mod:`shmu_opendata.radar`), this
    module only decodes.
    """

    quantity: str
    product: str
    width: int
    height: int
    gain: float
    offset: float
    nodata: float
    undetect: float
    #: Corner latitudes/longitudes (deg) from ODIM ``/where``: lower-left,
    #: upper-right — enough for a geographic extent on a Home Assistant map.
    ll_lat: float
    ll_lon: float
    ur_lat: float
    ur_lon: float
    projdef: str
    raw: bytes
    dtype: str


class _Hdf5File:
    """Parses the verified HDF5 v0/v1 subset out of an in-memory file."""

    def __init__(self, data: bytes) -> None:
        if data[:8] != b"\x89HDF\r\n\x1a\n":
            raise ShmuDataError("Not an HDF5 file (bad signature)")
        if data[8] != 0:
            raise ShmuDataError(
                f"Unsupported HDF5 superblock version {data[8]} (need 0)"
            )
        self._d = data
        self._off = data[13]  # size of offsets
        self._len = data[14]  # size of lengths
        if self._off != 8 or self._len != 8:
            raise ShmuDataError(
                f"Unsupported HDF5 offset/length size {self._off}/{self._len}"
            )
        # v0 superblock: base/freespace/eof/driver addresses (off-size each)
        # follow the 24-byte fixed prefix, then the root symbol-table entry.
        ste = 24 + 4 * self._off
        self._root = _u(data, ste + self._off, self._off)

    # -- object header / messages --------------------------------------------

    def _messages(self, oh_addr: int) -> list[tuple[int, int, int]]:
        """Return ``(type, body_offset, size)`` for one object's messages.

        Object header **v1** only: a 16-byte prefix then 8-byte-aligned
        messages, possibly spilling into continuation blocks (message 0x10).
        """
        d = self._d
        if d[oh_addr] != 1:
            raise ShmuDataError(
                f"Unsupported object header version {d[oh_addr]} (need 1)"
            )
        total = _u(d, oh_addr + 2, 2)
        first_size = _u(d, oh_addr + 8, 4)
        blocks = [(oh_addr + _OBJECT_HEADER_V1_PREFIX, first_size)]
        out: list[tuple[int, int, int]] = []
        while blocks and len(out) < total:
            start, size = blocks.pop(0)
            end = start + size
            pos = start
            while pos + 8 <= end and len(out) < total:
                mtype = _u(d, pos, 2)
                msize = _u(d, pos + 2, 2)
                body = pos + 8
                out.append((mtype, body, msize))
                if mtype == _MSG_CONTINUATION:
                    blocks.append(
                        (_u(d, body, self._off), _u(d, body + self._off, self._len))
                    )
                pos = body + msize
        return out

    # -- groups (symbol-table B-tree + local heap) ---------------------------

    def _heap_name(self, heap_addr: int, name_offset: int) -> str:
        d = self._d
        if d[heap_addr : heap_addr + 4] != b"HEAP":
            raise ShmuDataError("Malformed local heap")
        data_seg = _u(d, heap_addr + 8 + 2 * self._len, self._off)
        start = data_seg + name_offset
        end = d.index(b"\0", start)
        return d[start:end].decode("ascii")

    def _btree_children(self, btree_addr: int, heap_addr: int) -> dict[str, int]:
        d = self._d
        if d[btree_addr : btree_addr + 4] != b"TREE" or d[btree_addr + 4] != 0:
            raise ShmuDataError("Expected a group B-tree node")
        level = d[btree_addr + 5]
        entries = _u(d, btree_addr + 6, 2)
        # node: 8-byte prefix, two sibling pointers, then key0,
        # child0, key1, ... (group node keys are one length-sized heap offset).
        pos = btree_addr + 8 + 2 * self._off + self._len
        out: dict[str, int] = {}
        for _ in range(entries):
            child = _u(d, pos, self._off)
            pos += self._off + self._len
            if level > 0:
                out.update(self._btree_children(child, heap_addr))
            else:
                out.update(self._snod(child, heap_addr))
        return out

    def _snod(self, addr: int, heap_addr: int) -> dict[str, int]:
        d = self._d
        if d[addr : addr + 4] != b"SNOD":
            raise ShmuDataError("Expected a symbol-table node")
        count = _u(d, addr + 6, 2)
        pos = addr + 8
        out: dict[str, int] = {}
        for _ in range(count):
            name_off = _u(d, pos, self._off)
            obj_header = _u(d, pos + self._off, self._off)
            out[self._heap_name(heap_addr, name_off)] = obj_header
            # entry = 2 offsets + cache type (4) + reserved (4) + scratch (16)
            pos += 2 * self._off + 24
        return out

    def group_children(self, oh_addr: int, _depth: int = 0) -> dict[str, int]:
        """Resolve a group's immediate child name → object-header address."""
        if _depth > _MAX_GROUP_DEPTH:
            raise ShmuDataError("HDF5 group nesting too deep")
        for mtype, body, _size in self._messages(oh_addr):
            if mtype == _MSG_SYMBOL_TABLE:
                btree = _u(self._d, body, self._off)
                heap = _u(self._d, body + self._off, self._off)
                return self._btree_children(btree, heap)
        return {}

    def resolve(self, *path: str) -> int:
        """Return the object-header address at ``/path/...`` from the root."""
        addr = self._root
        for depth, name in enumerate(path):
            children = self.group_children(addr, depth)
            if name not in children:
                raise ShmuDataError(f"HDF5 path element {name!r} not found")
            addr = children[name]
        return addr

    # -- attributes ----------------------------------------------------------

    @staticmethod
    def _pad8(n: int) -> int:
        return (n + 7) & ~7

    def _read_attribute(self, body: int) -> tuple[str, AttrValue]:
        d = self._d
        if d[body] != 1:
            raise ShmuDataError(
                f"Unsupported attribute message version {d[body]} (need 1)"
            )
        name_size = _u(d, body + 2, 2)
        dt_size = _u(d, body + 4, 2)
        ds_size = _u(d, body + 6, 2)
        pos = body + 8
        name = d[pos : pos + name_size].split(b"\0", 1)[0].decode("ascii")
        pos += self._pad8(name_size)
        dt = pos
        dt_class = d[dt] & 0x0F
        elem_size = _u(d, dt + 4, 4)
        pos += self._pad8(dt_size)
        # ODIM attributes are scalars or rank-1; element count is the product
        # of the dataspace dims (1 for a scalar dataspace).
        rank = d[pos + 1]
        count = 1
        for i in range(rank):
            count *= _u(d, pos + 8 + i * 8, 8)
        pos += self._pad8(ds_size)
        payload = d[pos : pos + elem_size * count]
        if dt_class == 3:  # fixed-length string
            return name, payload.split(b"\0", 1)[0].decode("ascii", "replace")
        if dt_class == 1 and elem_size == 8:  # IEEE float64
            return name, float(struct.unpack_from("<d", payload)[0])
        if dt_class == 0:  # fixed-point integer (xsize/ysize are signed)
            return name, int.from_bytes(payload[:elem_size], "little", signed=True)
        raise ShmuDataError(
            f"Unsupported attribute datatype class {dt_class} for {name!r}"
        )

    def attributes(self, *path: str) -> dict[str, AttrValue]:
        """All attributes on the group at ``/path/...``."""
        out: dict[str, AttrValue] = {}
        for mtype, body, _size in self._messages(self.resolve(*path)):
            if mtype == _MSG_ATTRIBUTE:
                key, value = self._read_attribute(body)
                out[key] = value
        return out

    # -- the single composite dataset ----------------------------------------

    def read_dataset(self, *path: str) -> tuple[int, int, str, bytes]:
        """Return ``(width, height, dtype, raw)`` for a 2-D chunked dataset.

        Only the verified shape is accepted: 2-D, a single deflate-compressed
        chunk covering the whole array, ``u8`` (fixed-point, 1 byte) or
        ``f32`` (IEEE float, 4 byte) elements.
        """
        d = self._d
        msgs = {mt: body for mt, body, _s in self._messages(self.resolve(*path))}
        for required in (_MSG_DATASPACE, _MSG_DATATYPE, _MSG_DATA_LAYOUT):
            if required not in msgs:
                raise ShmuDataError(f"Dataset missing message {required:#x}")

        ds = msgs[_MSG_DATASPACE]
        rank = d[ds + 1]
        if rank != 2:
            raise ShmuDataError(f"Expected a 2-D dataset, got rank {rank}")
        height = _u(d, ds + 8, 8)
        width = _u(d, ds + 16, 8)

        dt = msgs[_MSG_DATATYPE]
        dt_class = d[dt] & 0x0F
        elem_size = _u(d, dt + 4, 4)
        if dt_class == 0 and elem_size == 1:
            dtype = "u8"
        elif dt_class == 1 and elem_size == 4:
            dtype = "f32"
        else:
            raise ShmuDataError(
                f"Unsupported dataset datatype class {dt_class} size {elem_size}"
            )

        self._require_deflate(msgs.get(_MSG_FILTER_PIPELINE))

        layout = msgs[_MSG_DATA_LAYOUT]
        if d[layout] != 3 or d[layout + 1] != 2:
            raise ShmuDataError("Unsupported data layout (need v3 chunked)")
        btree = _u(d, layout + 3, self._off)
        raw = self._read_single_chunk(btree, rank, width * height * elem_size)
        return width, height, dtype, raw

    def _require_deflate(self, pipeline_body: int | None) -> None:
        if pipeline_body is None:
            raise ShmuDataError("Dataset is not compressed (expected deflate)")
        d = self._d
        if d[pipeline_body] != 1:
            raise ShmuDataError("Unsupported filter-pipeline message version")
        first_filter_id = _u(d, pipeline_body + 8, 2)
        if d[pipeline_body + 1] < 1 or first_filter_id != _DEFLATE_FILTER_ID:
            raise ShmuDataError("Unsupported filter (only deflate is handled)")

    def _read_single_chunk(
        self, btree_addr: int, rank: int, expected_bytes: int
    ) -> bytes:
        d = self._d
        if d[btree_addr : btree_addr + 4] != b"TREE" or d[btree_addr + 4] != 1:
            raise ShmuDataError("Expected a raw-data chunk B-tree node")
        if d[btree_addr + 5] != 0:
            raise ShmuDataError("Multi-level chunk B-tree is unsupported")
        if _u(d, btree_addr + 6, 2) != 1:
            raise ShmuDataError("Expected exactly one chunk covering the array")
        # leaf key: chunk size (4) + filter mask (4) + (rank+1) offsets (8 ea.)
        pos = btree_addr + 8 + 2 * self._off
        chunk_size = _u(d, pos, 4)
        key_size = 8 + 8 * (rank + 1)
        chunk_addr = _u(d, pos + key_size, self._off)
        raw = zlib.decompress(d[chunk_addr : chunk_addr + chunk_size])
        if len(raw) != expected_bytes:
            raise ShmuDataError(
                f"Decompressed chunk is {len(raw)} bytes, expected {expected_bytes}"
            )
        return raw


def read_odim(data: bytes) -> OdimComposite:
    """Decode a SHMÚ ODIM_H5 radar composite file.

    Raises :class:`ShmuDataError` on anything outside the verified subset so
    an upstream format change fails loudly instead of producing a wrong image.
    """
    try:
        f = _Hdf5File(data)
        what = f.attributes("dataset1", "what")
        where = f.attributes("where")
        width, height, dtype, raw = f.read_dataset("dataset1", "data1", "data")
    except ShmuDataError:
        raise
    except (IndexError, ValueError, struct.error, zlib.error) as err:
        raise ShmuDataError(f"Malformed ODIM_H5 file: {err}") from err

    return OdimComposite(
        quantity=str(what.get("quantity", "")),
        product=str(what.get("product", "")),
        width=width,
        height=height,
        gain=float(what.get("gain", 1.0)),
        offset=float(what.get("offset", 0.0)),
        nodata=float(what.get("nodata", float("nan"))),
        undetect=float(what.get("undetect", float("nan"))),
        ll_lat=float(where.get("LL_lat", 0.0)),
        ll_lon=float(where.get("LL_lon", 0.0)),
        ur_lat=float(where.get("UR_lat", 0.0)),
        ur_lon=float(where.get("UR_lon", 0.0)),
        projdef=str(where.get("projdef", "")),
        raw=raw,
        dtype=dtype,
    )
