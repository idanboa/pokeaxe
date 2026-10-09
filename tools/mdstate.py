"""Read VRAM/CRAM/VDP registers from an OpenEmu (Genesis Plus GX 1.7.6) save state and render planes.
usage: python3 -E tools/mdstate.py <State file> <out prefix>"""
import struct, sys
from PIL import Image

VRAM = 0x12425          # found empirically; GPGX stores VRAM/CRAM byte-swapped per word


class State:
    def __init__(self, path):
        d = open(path, 'rb').read()
        sw = lambda b: bytes(b[i ^ 1] for i in range(len(b)))
        self.vram = sw(d[VRAM:VRAM + 0x10000])
        cram = d[VRAM + 0x10000:VRAM + 0x10080]
        self.cram = [struct.unpack_from('<H', cram, i * 2)[0] for i in range(64)]   # 9-bit BBBGGGRRR
        self.regs = d[VRAM + 0x10100:VRAM + 0x10120]

    def rgb(self, i):
        c = self.cram[i]
        return tuple(((c >> s) & 7) * 255 // 7 for s in (0, 3, 6))

    def tile(self, n):
        t = self.vram[n * 32:n * 32 + 32]
        return [[(t[r * 4 + c // 2] >> (4 if c % 2 == 0 else 0)) & 15 for c in range(8)] for r in range(8)]

    def plane(self, base, w, h):
        img = Image.new('RGB', (w * 8, h * 8))
        cells = {}
        for y in range(h):
            for x in range(w):
                e = struct.unpack_from('>H', self.vram, base + (y * w + x) * 2)[0]
                n, pal, hf, vf = e & 0x7ff, (e >> 13) & 3, e & 0x800, e & 0x1000
                cells[(x, y)] = e
                t = self.tile(n)
                for r in range(8):
                    for c in range(8):
                        v = t[7 - r if vf else r][7 - c if hf else c]
                        img.putpixel((x * 8 + c, y * 8 + r), self.rgb(pal * 16 + v) if v else (255, 0, 255))
        return img, cells


if __name__ == '__main__':
    s = State(sys.argv[1])
    r = s.regs
    print('regs', r.hex())
    sizes = {0: 32, 1: 64, 3: 128}
    pw, ph = sizes[r[16] & 3], sizes[(r[16] >> 4) & 3]
    a, win, b = (r[2] & 0x38) << 10, (r[3] & 0x3e) << 10, (r[4] & 7) << 13
    print(f'planeA {a:#x} window {win:#x} planeB {b:#x} size {pw}x{ph} win h/v {r[17]:#x}/{r[18]:#x}')
    for name, base, w, h in (('A', a, pw, ph), ('B', b, pw, ph), ('W', win, 64 if r[12] & 1 else 32, 32)):
        s.plane(base, w, h)[0].save(f'{sys.argv[2]}_{name}.png')
