"""Sega Nemesis tile compression (https://segaretro.org/Nemesis_compression).

decode() is a full decoder. encode() writes a valid but unoptimised stream: an empty code table
with every run sent through the inline escape (111111 + 3-bit count + 4-bit nibble). The game's
decompressor accepts it; it is just larger than Sega's originals.
"""


def decode(data, offset=0, max_tiles=None):
    """Return (tile bytes, compressed length)."""
    p = offset
    header = (data[p] << 8) | data[p + 1]
    p += 2
    xor, ntiles = header & 0x8000, header & 0x7FFF
    if max_tiles is not None and ntiles > max_tiles:
        raise ValueError('too many tiles')
    codes, nibble = {}, 0
    b = data[p]; p += 1
    while b != 0xFF:
        if b & 0x80:
            nibble = b & 0x0F
            b = data[p]; p += 1
            continue
        run, length, code = ((b >> 4) & 7) + 1, b & 0x0F, data[p]
        p += 1
        if not 1 <= length <= 8:
            raise ValueError('bad code length')
        codes[(length, code)] = (nibble, run)
        b = data[p]; p += 1

    bitpos = p * 8

    def bits(n):
        nonlocal bitpos
        v = 0
        for _ in range(n):
            if bitpos >> 3 >= len(data):
                raise ValueError('ran past end of data')
            v = (v << 1) | ((data[bitpos >> 3] >> (7 - (bitpos & 7))) & 1)
            bitpos += 1
        return v

    out, row, prev, nib_in_row = bytearray(), 0, 0, 0
    total = ntiles * 64
    produced = 0
    while produced < total:
        code, length, found = 0, 0, None
        while found is None:
            code = (code << 1) | bits(1)
            length += 1
            if length == 6 and code == 0x3F:
                v = bits(7)
                found = (v & 0x0F, ((v >> 4) & 7) + 1)
            elif (length, code) in codes:
                found = codes[(length, code)]
            elif length > 8:
                raise ValueError('invalid code')
        nib, run = found
        for _ in range(run):
            row = ((row << 4) | nib) & 0xFFFFFFFF
            nib_in_row += 1
            produced += 1
            if nib_in_row == 8:
                if xor:
                    row ^= prev
                    prev = row
                out += row.to_bytes(4, 'big')
                row, nib_in_row = 0, 0
            if produced == total:
                break
    return bytes(out), (bitpos + 7) // 8 - offset


def encode(tiles):
    """tiles: bytes, a multiple of 32 (4bpp 8x8 tiles). Returns a Nemesis stream."""
    assert len(tiles) % 32 == 0
    out = bytearray([(len(tiles) // 32) >> 8 & 0x7F, (len(tiles) // 32) & 0xFF, 0xFF])
    bitbuf, nbits = 0, 0

    def put(v, n):
        nonlocal bitbuf, nbits
        bitbuf = (bitbuf << n) | v
        nbits += n
        while nbits >= 8:
            nbits -= 8
            out.append((bitbuf >> nbits) & 0xFF)
        bitbuf &= (1 << nbits) - 1

    nibbles = [(b >> s) & 15 for b in tiles for s in (4, 0)]
    for r in range(0, len(nibbles), 8):          # keep runs inside a row
        row, i = nibbles[r:r + 8], 0
        while i < 8:
            j = i
            while j < 8 and j - i < 8 and row[j] == row[i]:
                j += 1
            put(0x3F, 6)
            put(((j - i - 1) << 4) | row[i], 7)
            i = j
    if nbits:
        put(0, 8 - nbits)
    return bytes(out)
