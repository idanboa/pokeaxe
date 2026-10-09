"""Readers for Golden Axe (Mega Drive, World Rev A) entity animation data.
Formats per jvisser/golden-axe-32x-edition doc/entityanimation.md and render.md."""
import struct

class Rom:
    def __init__(self, data): self.d = bytearray(data)
    def u8(self, a): return self.d[a]
    def s8(self, a): return struct.unpack_from('>b', self.d, a)[0]
    def u16(self, a): return struct.unpack_from('>H', self.d, a)[0]
    def s16(self, a): return struct.unpack_from('>h', self.d, a)[0]
    def u32(self, a): return struct.unpack_from('>I', self.d, a)[0]

def read_metasprite(rom, a):
    n = rom.u8(a) + 1
    ms = {'hurt': rom.u8(a+1), 'damage': rom.u8(a+2), 'sprites': []}
    p = a + 3
    for _ in range(n):
        ms['sprites'].append({'y': rom.s8(p), 'size': rom.u8(p+1), 'pat': rom.u16(p+2), 'x': rom.s8(p+4)})
        p += 5
    ms['end'] = p
    return ms

def read_dma_frame(rom, table, idx):
    a = rom.u32(table + idx*4); xfers = []
    while True:
        ln = rom.s16(a)
        if ln <= 0: break
        xfers.append((ln, rom.u16(a+2))); a += 4
    return xfers

def read_dma_animation(rom, a):
    anim = {'max': rom.u8(a), 'marker': rom.u8(a+1), 'count': rom.u8(a+2), 'time': rom.u8(a+3), 'frames': []}
    for i in range(anim['count']):
        fa = rom.u32(a + 4 + i*4)
        anim['frames'].append({'addr': fa, 'damage': rom.u8(fa), 'dma': rom.u8(fa+1), 'ms': read_metasprite(rom, fa+2)})
    return anim

def tiles(size): return (((size >> 2) & 3) + 1) * ((size & 3) + 1)


def read_preloaded_animation(rom, a):
    """PreLoadedAnimation: frameCount, frameTime, then frameCount metasprite pointers."""
    n = rom.u8(a)
    frames = []
    for i in range(n):
        p = rom.u32(a + 2 + i * 4)
        frames.append({'ptr_at': a + 2 + i * 4, 'ms_addr': p, 'ms': read_metasprite(rom, p)})
    return {'count': n, 'time': rom.u8(a + 1), 'frames': frames}
