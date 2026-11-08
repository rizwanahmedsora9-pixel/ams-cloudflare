"""A small, dependency-free QR encoder for the bill sheets.

Why this module exists
----------------------
The Urdu receipt prints a QR block in its header.  That QR used to come from
``segno`` (an optional pip extra), and when the package was missing on a host
the block was silently left blank - the sheet went out with no code at all.

This encoder is pure Python and always available, so a printed bill always
carries a scannable code.  ``segno`` is still preferred when it is installed
(it is battle-tested); this module is the fallback that removes the "the QR
disappeared after a deploy" class of failure.

What it implements
------------------
* Byte mode (UTF-8) - every payload this app prints is ASCII or UTF-8 Urdu.
* Versions 1-40, error-correction levels L/M/Q/H, automatic shrinking of the
  level (M -> L) when a payload only fits a larger symbol otherwise.
* Reed-Solomon blocks, interleaving, all eight data masks with the standard
  penalty rules, BCH format/version information.

The returned matrix is the symbol *without* a quiet zone (the caller adds it),
in row-major order, ``True`` = dark module - the same convention as
``segno.QRCode.matrix``.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

# (num_blocks, num_total_codewords, num_data_codewords) per block, in the
# symbol's own order.  Indexed [version][level]; level 0=L, 1=M, 2=Q, 3=H.
_ECC = {
    1: (((1, 26, 19),), ((1, 26, 16),),
        ((1, 26, 13),), ((1, 26, 9),)),
    2: (((1, 44, 34),), ((1, 44, 28),),
        ((1, 44, 22),), ((1, 44, 16),)),
    3: (((1, 70, 55),), ((1, 70, 44),),
        ((2, 35, 17),), ((2, 35, 13),)),
    4: (((1, 100, 80),), ((2, 50, 32),),
        ((2, 50, 24),), ((4, 25, 9),)),
    5: (((1, 134, 108),), ((2, 67, 43),),
        ((2, 33, 15), (2, 34, 16),), ((2, 33, 11), (2, 34, 12),)),
    6: (((2, 86, 68),), ((4, 43, 27),),
        ((4, 43, 19),), ((4, 43, 15),)),
    7: (((2, 98, 78),), ((4, 49, 31),),
        ((2, 32, 14), (4, 33, 15),), ((4, 39, 13), (1, 40, 14),)),
    8: (((2, 121, 97),), ((2, 60, 38), (2, 61, 39),),
        ((4, 40, 18), (2, 41, 19),), ((4, 40, 14), (2, 41, 15),)),
    9: (((2, 146, 116),), ((3, 58, 36), (2, 59, 37),),
        ((4, 36, 16), (4, 37, 17),), ((4, 36, 12), (4, 37, 13),)),
    10: (((2, 86, 68), (2, 87, 69),), ((4, 69, 43), (1, 70, 44),),
        ((6, 43, 19), (2, 44, 20),), ((6, 43, 15), (2, 44, 16),)),
    11: (((4, 101, 81),), ((1, 80, 50), (4, 81, 51),),
        ((4, 50, 22), (4, 51, 23),), ((3, 36, 12), (8, 37, 13),)),
    12: (((2, 116, 92), (2, 117, 93),), ((6, 58, 36), (2, 59, 37),),
        ((4, 46, 20), (6, 47, 21),), ((7, 42, 14), (4, 43, 15),)),
    13: (((4, 133, 107),), ((8, 59, 37), (1, 60, 38),),
        ((8, 44, 20), (4, 45, 21),), ((12, 33, 11), (4, 34, 12),)),
    14: (((3, 145, 115), (1, 146, 116),), ((4, 64, 40), (5, 65, 41),),
        ((11, 36, 16), (5, 37, 17),), ((11, 36, 12), (5, 37, 13),)),
    15: (((5, 109, 87), (1, 110, 88),), ((5, 65, 41), (5, 66, 42),),
        ((5, 54, 24), (7, 55, 25),), ((11, 36, 12), (7, 37, 13),)),
    16: (((5, 122, 98), (1, 123, 99),), ((7, 73, 45), (3, 74, 46),),
        ((15, 43, 19), (2, 44, 20),), ((3, 45, 15), (13, 46, 16),)),
    17: (((1, 135, 107), (5, 136, 108),), ((10, 74, 46), (1, 75, 47),),
        ((1, 50, 22), (15, 51, 23),), ((2, 42, 14), (17, 43, 15),)),
    18: (((5, 150, 120), (1, 151, 121),), ((9, 69, 43), (4, 70, 44),),
        ((17, 50, 22), (1, 51, 23),), ((2, 42, 14), (19, 43, 15),)),
    19: (((3, 141, 113), (4, 142, 114),), ((3, 70, 44), (11, 71, 45),),
        ((17, 47, 21), (4, 48, 22),), ((9, 39, 13), (16, 40, 14),)),
    20: (((3, 135, 107), (5, 136, 108),), ((3, 67, 41), (13, 68, 42),),
        ((15, 54, 24), (5, 55, 25),), ((15, 43, 15), (10, 44, 16),)),
    21: (((4, 144, 116), (4, 145, 117),), ((17, 68, 42),),
        ((17, 50, 22), (6, 51, 23),), ((19, 46, 16), (6, 47, 17),)),
    22: (((2, 139, 111), (7, 140, 112),), ((17, 74, 46),),
        ((7, 54, 24), (16, 55, 25),), ((34, 37, 13),)),
    23: (((4, 151, 121), (5, 152, 122),), ((4, 75, 47), (14, 76, 48),),
        ((11, 54, 24), (14, 55, 25),), ((16, 45, 15), (14, 46, 16),)),
    24: (((6, 147, 117), (4, 148, 118),), ((6, 73, 45), (14, 74, 46),),
        ((11, 54, 24), (16, 55, 25),), ((30, 46, 16), (2, 47, 17),)),
    25: (((8, 132, 106), (4, 133, 107),), ((8, 75, 47), (13, 76, 48),),
        ((7, 54, 24), (22, 55, 25),), ((22, 45, 15), (13, 46, 16),)),
    26: (((10, 142, 114), (2, 143, 115),), ((19, 74, 46), (4, 75, 47),),
        ((28, 50, 22), (6, 51, 23),), ((33, 46, 16), (4, 47, 17),)),
    27: (((8, 152, 122), (4, 153, 123),), ((22, 73, 45), (3, 74, 46),),
        ((8, 53, 23), (26, 54, 24),), ((12, 45, 15), (28, 46, 16),)),
    28: (((3, 147, 117), (10, 148, 118),), ((3, 73, 45), (23, 74, 46),),
        ((4, 54, 24), (31, 55, 25),), ((11, 45, 15), (31, 46, 16),)),
    29: (((7, 146, 116), (7, 147, 117),), ((21, 73, 45), (7, 74, 46),),
        ((1, 53, 23), (37, 54, 24),), ((19, 45, 15), (26, 46, 16),)),
    30: (((5, 145, 115), (10, 146, 116),), ((19, 75, 47), (10, 76, 48),),
        ((15, 54, 24), (25, 55, 25),), ((23, 45, 15), (25, 46, 16),)),
    31: (((13, 145, 115), (3, 146, 116),), ((2, 74, 46), (29, 75, 47),),
        ((42, 54, 24), (1, 55, 25),), ((23, 45, 15), (28, 46, 16),)),
    32: (((17, 145, 115),), ((10, 74, 46), (23, 75, 47),),
        ((10, 54, 24), (35, 55, 25),), ((19, 45, 15), (35, 46, 16),)),
    33: (((17, 145, 115), (1, 146, 116),), ((14, 74, 46), (21, 75, 47),),
        ((29, 54, 24), (19, 55, 25),), ((11, 45, 15), (46, 46, 16),)),
    34: (((13, 145, 115), (6, 146, 116),), ((14, 74, 46), (23, 75, 47),),
        ((44, 54, 24), (7, 55, 25),), ((59, 46, 16), (1, 47, 17),)),
    35: (((12, 151, 121), (7, 152, 122),), ((12, 75, 47), (26, 76, 48),),
        ((39, 54, 24), (14, 55, 25),), ((22, 45, 15), (41, 46, 16),)),
    36: (((6, 151, 121), (14, 152, 122),), ((6, 75, 47), (34, 76, 48),),
        ((46, 54, 24), (10, 55, 25),), ((2, 45, 15), (64, 46, 16),)),
    37: (((17, 152, 122), (4, 153, 123),), ((29, 74, 46), (14, 75, 47),),
        ((49, 54, 24), (10, 55, 25),), ((24, 45, 15), (46, 46, 16),)),
    38: (((4, 152, 122), (18, 153, 123),), ((13, 74, 46), (32, 75, 47),),
        ((48, 54, 24), (14, 55, 25),), ((42, 45, 15), (32, 46, 16),)),
    39: (((20, 147, 117), (4, 148, 118),), ((40, 75, 47), (7, 76, 48),),
        ((43, 54, 24), (22, 55, 25),), ((10, 45, 15), (67, 46, 16),)),
    40: (((19, 148, 118), (6, 149, 119),), ((18, 75, 47), (31, 76, 48),),
        ((34, 54, 24), (34, 55, 25),), ((20, 45, 15), (61, 46, 16),)),
}

# Alignment pattern centre coordinates per version.
_ALIGNMENT = {
    1: (), 2: (6, 18), 3: (6, 22), 4: (6, 26), 5: (6, 30), 6: (6, 34),
    7: (6, 22, 38), 8: (6, 24, 42), 9: (6, 26, 46), 10: (6, 28, 50),
    11: (6, 30, 54), 12: (6, 32, 58), 13: (6, 34, 62), 14: (6, 26, 46, 66),
    15: (6, 26, 48, 70), 16: (6, 26, 50, 74), 17: (6, 30, 54, 78),
    18: (6, 30, 56, 82), 19: (6, 30, 58, 86), 20: (6, 34, 62, 90),
    21: (6, 28, 50, 72, 94), 22: (6, 26, 50, 74, 98),
    23: (6, 30, 54, 78, 102), 24: (6, 28, 54, 80, 106),
    25: (6, 32, 58, 84, 110), 26: (6, 30, 58, 86, 114),
    27: (6, 34, 62, 90, 118), 28: (6, 26, 50, 74, 98, 122),
    29: (6, 30, 54, 78, 102, 126), 30: (6, 26, 52, 78, 104, 130),
    31: (6, 30, 56, 82, 108, 134), 32: (6, 34, 60, 86, 112, 138),
    33: (6, 30, 58, 86, 114, 142), 34: (6, 34, 62, 90, 118, 146),
    35: (6, 30, 54, 78, 102, 126, 150), 36: (6, 24, 50, 76, 102, 128, 154),
    37: (6, 28, 54, 80, 106, 132, 158), 38: (6, 32, 58, 84, 110, 136, 162),
    39: (6, 26, 54, 82, 110, 138, 166), 40: (6, 30, 58, 86, 114, 142, 170),
}

_LEVELS = {'l': 0, 'm': 1, 'q': 2, 'h': 3}
# Two-bit indicator written in the format information, per level.
_FORMAT_LEVEL = {0: 1, 1: 0, 2: 3, 3: 2}
MODE_BYTE = 0x4


# ---------------------------------------------------------------------------
# GF(256) arithmetic and Reed-Solomon
# ---------------------------------------------------------------------------

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        # multiply poly by (x - a^i)
        root = _EXP[i]
        out = [0] * (len(poly) + 1)
        for j, coeff in enumerate(poly):
            out[j] ^= coeff
            out[j + 1] ^= _mul(coeff, root)
        poly = out
    return poly


_GEN_CACHE: dict[int, list[int]] = {}


def _rs_ec(data: list[int], degree: int) -> list[int]:
    gen = _GEN_CACHE.get(degree)
    if gen is None:
        gen = _GEN_CACHE[degree] = _rs_generator(degree)
    remainder = list(data) + [0] * degree
    for i in range(len(data)):
        factor = remainder[i]
        if factor == 0:
            continue
        for j, coeff in enumerate(gen):
            remainder[i + j] ^= _mul(coeff, factor)
    return remainder[-degree:] if degree else []


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _capacity_bits(version: int, level: int) -> int:
    blocks = _ECC[version][level]
    data_codewords = sum(b[0] * b[2] for b in blocks)
    return data_codewords * 8


# Mode selectors (ISO/IEC 18004 table 2).  Byte mode is the fallback because
# the far side must be able to read ANY payload; alphanumeric and numeric are
# used when they fit because each packs a payload into fewer modules, i.e. a
# coarser, easier-to-scan symbol on paper.
MODE_NUMERIC = 0x1
MODE_ALPHANUMERIC = 0x2
MODE_BYTE = 0x4

# The 45 characters of alphanumeric mode, in encoding order.  A printed link
# such as ``https://shop.example.com/b/S42.SBSL1008.X7K2MQ9BT1`` is entirely
# inside this set once the URL is upper-cased (DNS names are case-insensitive
# and Flask routes match case-insensitively for the token we emit), so it
# encodes at 5.5 bits per character instead of 8.
_ALNUM = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
_ALNUM_INDEX = {ch: i for i, ch in enumerate(_ALNUM)}


def _mode_for(text: str) -> str:
    """``'n'`` / ``'a'`` / ``'b'`` - the densest mode that can hold *text*."""
    if not text:
        return 'b'
    if all(ch in '0123456789' for ch in text):
        return 'n'
    if all(ch in _ALNUM_INDEX for ch in text):
        return 'a'
    return 'b'


def _count_bits(mode: str, version: int) -> int:
    """Character-count indicator width for *mode* at *version*."""
    small = version <= 9
    if mode == 'n':
        return 10 if small else (12 if version <= 26 else 14)
    if mode == 'a':
        return 9 if small else (11 if version <= 26 else 13)
    return 8 if small else 16


def _payload_bits(mode: str, text: str) -> tuple[int, int]:
    """``(character count, bit length)`` of *text* in *mode*."""
    if mode == 'n':
        groups, rest = divmod(len(text), 3)
        return len(text), groups * 10 + (0 if not rest else (4 if rest == 1 else 7))
    if mode == 'a':
        pairs, rest = divmod(len(text), 2)
        return len(text), pairs * 11 + rest * 6
    payload = text.encode('utf-8')
    return len(payload), len(payload) * 8


def _pick_version(text: str, level: int) -> tuple[int, int, str] | None:
    """Smallest version (and the level and mode actually used) for *text*."""
    mode = _mode_for(text)
    length, body_bits = _payload_bits(mode, text)
    for candidate in (level, level + 1, level + 2, level + 3):
        if candidate > 3:
            break
        for version in range(1, 41):
            needed = 4 + _count_bits(mode, version) + body_bits
            if needed <= _capacity_bits(version, candidate):
                return version, candidate, mode
    return None


def _data_codewords(text: str, version: int, level: int,
                     mode: str | None = None) -> list[int]:
    blocks = _ECC[version][level]
    capacity = sum(b[0] * b[2] for b in blocks) * 8
    bits: list[int] = []
    mode = mode or _mode_for(text)

    def push(value: int, width: int) -> None:
        for shift in range(width - 1, -1, -1):
            bits.append((value >> shift) & 1)

    if mode == 'n':
        push(MODE_NUMERIC, 4)
        push(len(text), _count_bits(mode, version))
        for start in range(0, len(text), 3):
            chunk = text[start:start + 3]
            push(int(chunk), {3: 10, 2: 7, 1: 4}[len(chunk)])
    elif mode == 'a':
        push(MODE_ALPHANUMERIC, 4)
        push(len(text), _count_bits(mode, version))
        for start in range(0, len(text), 2):
            chunk = text[start:start + 2]
            if len(chunk) == 2:
                push(_ALNUM_INDEX[chunk[0]] * 45 + _ALNUM_INDEX[chunk[1]], 11)
            else:
                push(_ALNUM_INDEX[chunk[0]], 6)
    else:
        payload = text.encode('utf-8')
        push(MODE_BYTE, 4)
        push(len(payload), _count_bits('b', version))
        for byte in payload:
            push(byte, 8)

    # Terminator (up to four zero bits), then pad to a byte boundary.
    for _ in range(min(4, capacity - len(bits))):
        bits.append(0)
    while len(bits) % 8:
        bits.append(0)

    words = [int(''.join(str(b) for b in bits[i:i + 8]), 2)
             for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    index = 0
    while len(words) * 8 < capacity:
        words.append(pad[index % 2])
        index += 1
    return words


def _interleave(data: list[int], version: int, level: int) -> list[int]:
    groups = _ECC[version][level]
    blocks: list[list[int]] = []
    ec_blocks: list[list[int]] = []
    offset = 0
    for count, total, data_len in groups:
        ec_len = total - data_len
        for _ in range(count):
            chunk = data[offset:offset + data_len]
            offset += data_len
            blocks.append(chunk)
            ec_blocks.append(_rs_ec(chunk, ec_len))
    out: list[int] = []
    for column in range(max(len(b) for b in blocks)):
        for block in blocks:
            if column < len(block):
                out.append(block[column])
    for column in range(max(len(b) for b in ec_blocks)):
        for block in ec_blocks:
            if column < len(block):
                out.append(block[column])
    return out


def _bit_stream(codewords: list[int]) -> list[int]:
    bits: list[int] = []
    for word in codewords:
        for shift in range(7, -1, -1):
            bits.append((word >> shift) & 1)
    return bits


# ---------------------------------------------------------------------------
# Matrix construction
# ---------------------------------------------------------------------------

class _Grid:
    """Symbol canvas: ``None`` = still free, ``True``/``False`` = reserved."""

    def __init__(self, version: int):
        self.version = version
        self.size = 17 + 4 * version
        self.cells = [[None] * self.size for _ in range(self.size)]

    # -- function patterns -------------------------------------------------
    def _set(self, row: int, col: int, dark: bool) -> None:
        self.cells[row][col] = dark

    def _finder(self, row: int, col: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                r, c = row + dr, col + dc
                if not (0 <= r < self.size and 0 <= c < self.size):
                    continue
                inside = 0 <= dr <= 6 and 0 <= dc <= 6
                dark = False
                if inside:
                    # 0 = dark border, 1 = light ring, 2/3 = dark 3x3 core
                    ring = min(dr, dc, 6 - dr, 6 - dc)
                    dark = ring != 1
                self._set(r, c, dark)

    def function_patterns(self) -> None:
        size = self.size
        for row, col in ((0, 0), (0, size - 7), (size - 7, 0)):
            self._finder(row, col)
        for i in range(8, size - 8):
            dark = i % 2 == 0
            if self.cells[6][i] is None:
                self._set(6, i, dark)
            if self.cells[i][6] is None:
                self._set(i, 6, dark)
        for row in _ALIGNMENT[self.version]:
            for col in _ALIGNMENT[self.version]:
                if (row, col) in ((6, 6), (6, size - 7), (size - 7, 6)):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        self._set(row + dr, col + dc,
                                  max(abs(dr), abs(dc)) != 1)
        # Reserve the format areas and the dark module.
        for i in range(9):
            for r, c in ((8, i), (i, 8)):
                if self.cells[r][c] is None:
                    self._set(r, c, False)
        for i in range(8):
            if self.cells[8][size - 1 - i] is None:
                self._set(8, size - 1 - i, False)
            if self.cells[size - 1 - i][8] is None:
                self._set(size - 1 - i, 8, False)
        self._set(size - 8, 8, True)          # always-dark module
        if self.version >= 7:
            for i in range(6):
                for j in range(3):
                    if self.cells[i][size - 11 + j] is None:
                        self._set(i, size - 11 + j, False)
                    if self.cells[size - 11 + j][i] is None:
                        self._set(size - 11 + j, i, False)

    # -- data --------------------------------------------------------------
    def place_data(self, bits: list[int]) -> None:
        size = self.size
        index = 0
        total = len(bits)
        upward = True
        col = size - 1
        while col > 0:
            if col == 6:                       # skip the vertical timing column
                col -= 1
            rows = range(size - 1, -1, -1) if upward else range(size)
            for row in rows:
                for c in (col, col - 1):
                    if self.cells[row][c] is not None:
                        continue
                    self.cells[row][c] = bool(bits[index]) if index < total else False
                    index += 1
            upward = not upward
            col -= 2

    # -- masks -------------------------------------------------------------
    @staticmethod
    def mask_bit(mask: int, row: int, col: int) -> bool:
        if mask == 0:
            return (row + col) % 2 == 0
        if mask == 1:
            return row % 2 == 0
        if mask == 2:
            return col % 3 == 0
        if mask == 3:
            return (row + col) % 3 == 0
        if mask == 4:
            return (row // 2 + col // 3) % 2 == 0
        if mask == 5:
            return (row * col) % 2 + (row * col) % 3 == 0
        if mask == 6:
            return ((row * col) % 2 + (row * col) % 3) % 2 == 0
        return ((row + col) % 2 + (row * col) % 3) % 2 == 0

    def apply_mask(self, mask: int, reserved: list[list[bool]]) -> "_Grid":
        out = _Grid(self.version)
        for row in range(self.size):
            for col in range(self.size):
                dark = self.cells[row][col]
                if not reserved[row][col] and self.mask_bit(mask, row, col):
                    dark = not dark
                out.cells[row][col] = dark
        return out

    # -- penalty -----------------------------------------------------------
    def penalty(self) -> int:
        size = self.size
        score = 0
        for rows in (self.cells, [list(col) for col in zip(*self.cells)]):
            for line in rows:
                run_colour, run_len = line[0], 1
                for cell in line[1:]:
                    if cell == run_colour:
                        run_len += 1
                    else:
                        if run_len >= 5:
                            score += 3 + (run_len - 5)
                        run_colour, run_len = cell, 1
                if run_len >= 5:
                    score += 3 + (run_len - 5)
                # 1:1:3:1:1 finder-like sequence framed by four light modules
                pattern = [True, False, True, True, True, False, True]
                for i in range(len(line) - 6):
                    if line[i:i + 7] == pattern:
                        before = line[i - 4:i] if i >= 4 else None
                        after = line[i + 7:i + 11]
                        if (before is None or not any(before)) or \
                                (len(after) < 4 or not any(after)):
                            score += 40
        dark = sum(1 for row in self.cells for cell in row if cell)
        total = size * size
        percent = dark * 100 // total
        score += 10 * min(abs(percent - 50) // 5, 10)
        for row in range(size - 1):
            for col in range(size - 1):
                block = (self.cells[row][col], self.cells[row][col + 1],
                         self.cells[row + 1][col], self.cells[row + 1][col + 1])
                if all(block) or not any(block):
                    score += 3
        return score

    # -- information areas -------------------------------------------------
    def write_format(self, level: int, mask: int) -> None:
        data = (_FORMAT_LEVEL[level] << 3) | mask
        remainder = data
        for _ in range(10):
            remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
        bits = ((data << 10) | remainder) ^ 0x5412
        size = self.size
        for i in range(15):
            dark = bool((bits >> i) & 1)
            if i < 6:
                self._set(i, 8, dark)
            elif i == 6:
                self._set(7, 8, dark)
            elif i == 7:
                self._set(8, 8, dark)
            elif i == 8:
                self._set(8, 7, dark)
            else:
                self._set(8, 14 - i, dark)
            if i < 8:
                self._set(8, size - 1 - i, dark)
            else:
                self._set(size - 15 + i, 8, dark)
        self._set(size - 8, 8, True)

    def write_version(self) -> None:
        if self.version < 7:
            return
        remainder = self.version
        for _ in range(12):
            remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
        bits = (self.version << 12) | remainder
        size = self.size
        for i in range(18):
            dark = bool((bits >> i) & 1)
            row, col = i // 3, i % 3
            self._set(row, size - 11 + col, dark)
            self._set(size - 11 + col, row, dark)


def _reserved_map(version: int) -> list[list[bool]]:
    """``True`` where a module belongs to a function pattern."""
    probe = _Grid(version)
    probe.function_patterns()
    return [[cell is not None for cell in row] for row in probe.cells]


def make_matrix(text: str, error: str = 'm',
                mask: int | None = None) -> list[list[bool]] | None:
    """Return the QR matrix for *text* (no quiet zone), or ``None``.

    ``error`` is one of ``l``/``m``/``q``/``h``; the level steps down
    (M -> L, Q -> M ...) only when the payload would otherwise need a bigger
    symbol, which keeps a printed code readable.
    """
    text = text or ''
    if not text:
        return None
    level = _LEVELS.get(str(error or 'm').lower()[:1], 1)
    if level not in _LEVELS.values():
        level = 1
    chosen = _pick_version(text, level)
    if chosen is None:
        return None
    version, level, mode = chosen

    reserved = _reserved_map(version)
    base = _Grid(version)
    base.function_patterns()
    base.place_data(_bit_stream(_interleave(
        _data_codewords(text, version, level, mode), version, level)))

    best = None
    best_score = None
    masks = [mask] if mask is not None else range(8)
    for candidate_mask in masks:
        candidate = base.apply_mask(candidate_mask, reserved)
        candidate.write_format(level, candidate_mask)
        candidate.write_version()
        score = candidate.penalty()
        if best_score is None or score < best_score:
            best, best_score = candidate, score
    if best is None:
        return None
    return [[bool(cell) for cell in row] for row in best.cells]
