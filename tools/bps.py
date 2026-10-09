"""Minimal BPS patch writer and applier (https://www.romhacking.net/documents/746/).

usage: python3 -E tools/bps.py create <source> <target> <patch.bps>
       python3 -E tools/bps.py apply  <source> <patch.bps> <target>
"""
import sys
import zlib


def _num(n):
    out = bytearray()
    while True:
        x = n & 0x7F
        n >>= 7
        if n == 0:
            out.append(0x80 | x)
            return bytes(out)
        out.append(x)
        n -= 1


def _read_num(data, p):
    n, shift = 0, 1
    while True:
        x = data[p]
        p += 1
        n += (x & 0x7F) * shift
        if x & 0x80:
            return n, p
        shift <<= 7
        n += shift


def create(src, dst, metadata=b''):
    """Simple patch: SourceRead where bytes match at the same offset, TargetRead otherwise."""
    out = bytearray(b'BPS1') + _num(len(src)) + _num(len(dst)) + _num(len(metadata)) + metadata
    i = 0
    while i < len(dst):
        same = i < len(src) and src[i] == dst[i]
        j = i
        while j < len(dst) and (j < len(src) and src[j] == dst[j]) == same:
            j += 1
        if same:
            out += _num(((j - i - 1) << 2) | 0)
        else:
            out += _num(((j - i - 1) << 2) | 1) + dst[i:j]
        i = j
    out += zlib.crc32(src).to_bytes(4, 'little') + zlib.crc32(dst).to_bytes(4, 'little')
    out += zlib.crc32(out).to_bytes(4, 'little')
    return bytes(out)


def apply(src, patch):
    assert patch[:4] == b'BPS1', 'not a BPS patch'
    assert zlib.crc32(patch[:-4]) == int.from_bytes(patch[-4:], 'little'), 'patch checksum mismatch'
    assert zlib.crc32(src) == int.from_bytes(patch[-12:-8], 'little'), 'wrong source ROM'
    p = 4
    ssize, p = _read_num(patch, p)
    tsize, p = _read_num(patch, p)
    msize, p = _read_num(patch, p)
    p += msize
    out = bytearray()
    sp = tp = 0
    while p < len(patch) - 12:
        data, p = _read_num(patch, p)
        cmd, length = data & 3, (data >> 2) + 1
        if cmd == 0:
            out += src[len(out):len(out) + length]
        elif cmd == 1:
            out += patch[p:p + length]
            p += length
        else:
            off, p = _read_num(patch, p)
            off = (-1 if off & 1 else 1) * (off >> 1)
            if cmd == 2:
                sp += off
                out += src[sp:sp + length]
                sp += length
            else:
                tp += off
                for _ in range(length):
                    out.append(out[tp])
                    tp += 1
    assert len(out) == tsize and zlib.crc32(out) == int.from_bytes(patch[-8:-4], 'little'), 'output checksum mismatch'
    return bytes(out)


if __name__ == '__main__':
    mode, a, b, c = sys.argv[1:5]
    if mode == 'create':
        open(c, 'wb').write(create(open(a, 'rb').read(), open(b, 'rb').read()))
    else:
        open(c, 'wb').write(apply(open(a, 'rb').read(), open(b, 'rb').read()))
