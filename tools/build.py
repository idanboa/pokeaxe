"""Build the PokeAxe ROM: Golden Axe (Mega Drive, World Rev A) with characters reskinned as
PMD SpriteCollab Pokémon.

Every original animation, timing and hit box is kept; only frame graphics, sprite layouts and
palettes change. New data goes into a ROM expansion area past 512 KiB.

usage: python3 -E tools/build.py tools/mod.json <in.md> <out.md>
"""
import json, os, struct, sys
import xml.etree.ElementTree as ET
from collections import Counter
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from garom import Rom, read_dma_animation, read_preloaded_animation, tiles
import nemesis
import cries
import subprocess, tempfile

DIRS = {'down': 0, 'downright': 1, 'right': 2, 'upright': 3, 'up': 4, 'upleft': 5, 'left': 6, 'downleft': 7}


def md_color(rgb):
    r, g, b = (min(7, round(c / 255 * 7)) for c in rgb[:3])
    return (b << 9) | (g << 5) | (r << 1)


def md_rgb(w):
    return tuple(((w >> s) & 7) * 255 // 7 for s in (1, 5, 9))


def dist2(a, b):
    # weighted RGB distance; green matters most to the eye
    return 2 * (a[0] - b[0]) ** 2 + 4 * (a[1] - b[1]) ** 2 + 3 * (a[2] - b[2]) ** 2


class Pmd:
    def __init__(self, folder):
        self.folder = folder
        self.anims = {a.findtext('Name'): a for a in ET.parse(f'{folder}/AnimData.xml').getroot().iter('Anim')}
        self.sheets = {}

    def resolve(self, names):
        for n in names:
            if n in self.anims:
                a = self.anims[n]
                while a.findtext('CopyOf'):
                    n = a.findtext('CopyOf')
                    a = self.anims[n]
                return n, a
        sys.exit(f'{self.folder}: none of {names} available')

    def frame_count(self, names):
        name, a = self.resolve(names)
        return len(list(a.iter('Duration')))

    def frame(self, names, index, direction):
        """(RGBA image, anchor at the shadow centre)"""
        name, a = self.resolve(names)
        fw, fh = int(a.findtext('FrameWidth')), int(a.findtext('FrameHeight'))
        if name not in self.sheets:
            self.sheets[name] = (Image.open(f'{self.folder}/{name}-Anim.png').convert('RGBA'),
                                 Image.open(f'{self.folder}/{name}-Shadow.png').convert('RGBA'))
        sheet, shadow = self.sheets[name]
        row = DIRS[direction] if sheet.height // fh > 1 else 0
        box = (index * fw, row * fh, (index + 1) * fw, (row + 1) * fh)
        img, sh = sheet.crop(box), shadow.crop(box)
        pts = [(x, y) for y in range(fh) for x in range(fw) if sh.getpixel((x, y))[3]]
        anchor = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else (fw / 2, fh - 4)
        return img, anchor


# ---------------------------------------------------------------- pictures

def preloaded_halves(rom, ch):
    """(unflipped half, all animation addresses) for a preloaded entity's two-sided table."""
    n = ch['animation_count']
    def flipped(h):
        a = read_preloaded_animation(rom, rom.u32(ch['animation_table'] + h * n * 4))
        return bool(a['frames'][0]['ms']['sprites'][0]['pat'] & 0x800)
    return (0 if not flipped(0) else 1)


def preloaded_feet(rom, ch):
    half = preloaded_halves(rom, ch)
    ms = read_preloaded_animation(rom, rom.u32(ch['animation_table'] + half * ch['animation_count'] * 4))['frames'][0]['ms']
    return max(sp['y'] + ((sp['size'] & 3) + 1) * 8 for sp in ms['sprites']) - 2


def preloaded_pictures(rom, ch, presets, root):
    """(animation, frame) -> (pose key, variants) for a preloaded entity; few poses to fit VRAM."""
    pmd = Pmd(os.path.join(root, ch['pmd']))
    scale = ch['scale']
    amap = presets[ch['animations']] if isinstance(ch['animations'], str) else ch['animations']
    out, cache = {}, {}
    for a, spec in amap.items():
        a = int(a)
        names = spec['anim'] if isinstance(spec['anim'], list) else [spec['anim']]
        name = pmd.resolve(names)[0]
        n = pmd.frame_count(names)
        pick = [min(i, n - 1) if i >= 0 else n + i for i in spec.get('pick', [0])]
        count = max(read_preloaded_animation(rom, rom.u32(ch['animation_table'] + (h * ch['animation_count'] + a) * 4))['count']
                    for h in (0, 1))
        for j in range(count):
            idx = pick[j % len(pick)]
            key = (name, idx, spec.get('dir', 'left'))
            if key not in cache:
                im, (ax, ay) = pmd.frame(names, idx, key[2])
                cache[key] = [(im.resize((round(im.width * scale), round(im.height * scale)), Image.NEAREST), ax * scale, ay * scale)]
            out[(a, j)] = (key, cache[key])
    return out


def character_pictures(rom, ch, presets, root):
    """Map each DMA picture index of a character to a scaled PMD frame."""
    if ch.get('kind') == 'preloaded':
        return preloaded_pictures(rom, ch, presets, root)
    pmd = Pmd(os.path.join(root, ch['pmd']))
    scale = ch['scale']
    picks = {}
    if 'pictures' in ch:
        for k, (anim, idx, direction) in ch['pictures'].items():
            picks[int(k)] = ([anim], idx, direction)
    if 'animations' in ch:
        amap = presets[ch['animations']] if isinstance(ch['animations'], str) else ch['animations']
        for a, spec in amap.items():
            names, direction = spec['anim'], spec.get('dir', 'left')
            names = [names] if isinstance(names, str) else names
            n = pmd.frame_count(names)
            lo, hi = spec.get('frames', [0, n])
            hi = min(hi, n)
            # the left-facing (unflipped) table holds the pictures as stored
            anim = read_dma_animation(rom, rom.u32(ch['animation_table'] + (int(a) + ch['animation_count']) * 4))
            m = len(anim['frames'])
            for j, f in enumerate(anim['frames']):
                picks.setdefault(f['dma'], (names, lo + (j * (hi - lo)) // m, direction))
    boxes = damage_boxes(rom, ch) if 'effect' in ch else {}
    out, cache = {}, {}
    for d, (names, idx, direction) in picks.items():
        key = (pmd.resolve(names)[0], idx, direction, boxes.get(d))
        if key in cache:
            out[d] = (key, cache[key])
            continue
        im, (ax, ay) = pmd.frame(names, idx, direction)
        im, ax, ay = im.resize((im.width * scale, im.height * scale), Image.NEAREST), ax * scale, ay * scale
        variants = [(im, ax, ay)]
        if d in boxes:
            for amount in (1.0, 0.6, 0.35):   # full effect, then lighter ones if over the tile budget
                fx = dict(ch['effect'], amount=amount)
                e, ex, ey = draw_effect(im, ax, ay - ch['feet_y'], boxes[d], fx, seed=d)
                variants.insert(-1, (e, ex, ey + ch['feet_y']))
        # last resort for an oversized pose: the plain frame drawn a little smaller
        base, (bx0, by0) = pmd.frame(names, idx, direction)
        for f in (0.875, 0.75):
            sc = scale * f
            variants.append((base.resize((round(base.width * sc), round(base.height * sc)), Image.NEAREST), bx0 * sc, by0 * sc))
        cache[key] = variants
        out[d] = (key, variants)
    return out


def damage_boxes(rom, ch):
    """Picture index -> damage box (x, y, w, h) relative to the entity origin, from the left-facing table."""
    boxes = {}
    for a in range(ch['animation_count'], ch['animation_count'] * 2):
        for f in read_dma_animation(rom, rom.u32(ch['animation_table'] + a * 4))['frames']:
            i = f['ms']['damage']
            if i:
                b = ch['bounds_table'] + i * 8
                boxes.setdefault(f['dma'], (rom.s16(b), rom.s16(b + 4), rom.u16(b + 2), rom.u16(b + 6)))
    return boxes


def draw_effect(im, ax, ay, box, fx, seed=0):
    """Fill the damage box with element particles so the visible attack matches the real reach.
    Drawn on a half-resolution layer and scaled 2x to match the sprites' pixel size.
    ax/ay: entity origin inside im. Returns the (possibly enlarged) image and the moved origin."""
    import math, random
    from PIL import ImageDraw
    bx, by, bw, bh = box
    left, top = min(0, round(ax + bx)), min(0, round(ay + by))
    right, bottom = max(im.width, round(ax + bx + bw)), max(im.height, round(ay + by + bh))
    left -= left % 2; top -= top % 2
    w, h = right - left + (right - left) % 2, bottom - top + (bottom - top) % 2
    canvas = Image.new('RGBA', (w, h))
    canvas.alpha_composite(im, (-left, -top))
    ax, ay = ax - left, ay - top
    layer = Image.new('RGBA', (w // 2, h // 2))
    d = ImageDraw.Draw(layer)
    rnd = random.Random(seed)
    x0, y0 = (ax + bx) / 2, (ay + by) / 2
    hw, hh = bw / 2, bh / 2
    n = max(1, round(fx.get('count', 4) * fx.get('amount', 1.0)))
    c = [tuple(col) + (255,) for col in fx['colors']]
    for k in range(n):
        # spread along the box, further particles smaller
        t = (k + rnd.random() * 0.8) / n
        px = x0 + hw * (t if bx + bw / 2 > 0 else 1 - t)
        py = y0 + hh * (0.25 + 0.5 * rnd.random())
        size = (1.0 - 0.4 * t) * fx.get('size', 4)
        style = fx['style']
        if style == 'fire':                  # teardrop flame: dark rim, orange body, yellow core
            r = size
            d.polygon([(px - r, py), (px, py - 2.2 * r), (px + r, py), (px, py + r)], fill=c[0])
            d.polygon([(px - r * 0.55, py), (px, py - 1.5 * r), (px + r * 0.55, py), (px, py + r * 0.55)], fill=c[1])
            d.ellipse([px - r * 0.3, py - r * 0.3, px + r * 0.3, py + r * 0.3], fill=c[2])
        elif style == 'water':               # bubble ring with a highlight, plus a droplet
            r = size * 0.8
            d.ellipse([px - r, py - r, px + r, py + r], outline=c[0], width=1)
            d.point((px - r * 0.4, py - r * 0.4), fill=c[1])
            q = rnd.uniform(-hh * 0.3, hh * 0.3)
            d.ellipse([px + 2, py + q, px + 3, py + q + 1], fill=c[1])
        elif style == 'leaf':                # razor leaf: rotated lens with a light midrib
            ang = rnd.uniform(0, math.pi)
            L, W = size * 1.4, size * 0.6
            pts = [(px + L * math.cos(ang + a2) * (1 if i % 2 == 0 else W / L), py + L * math.sin(ang + a2) * (1 if i % 2 == 0 else W / L))
                   for i, a2 in enumerate((0, math.pi / 2, math.pi, 3 * math.pi / 2))]
            d.polygon(pts, fill=c[0])
            d.line([pts[0], pts[2]], fill=c[1])
        elif style == 'spark':               # zigzag bolt
            pts = [(px - size, py - size)]
            for _ in range(3):
                pts.append((pts[-1][0] + size * 0.7, pts[-1][1] + rnd.choice((-1, 1)) * size))
            d.line(pts, fill=c[0], width=2)
            d.line(pts, fill=c[1], width=1)
    canvas.alpha_composite(layer.resize((w, h), Image.NEAREST))
    return canvas, ax, ay


# ---------------------------------------------------------------- palettes

def build_group_palette(rom, group, images):
    """Return {slot: md colour} using the group's fixed colours plus k-means over the free slots."""
    base = group['palettes'][0]
    fixed = {s: rom.u16(base + 2 + s * 2) for s in group['fixed']}
    fixed.update({int(s): w for s, w in group.get('fixed_values', {}).items()})
    counts = Counter()
    for im in images:
        counts.update(md_color(p) for p in im.getdata() if p[3] >= 128)
    fixed_rgb = [md_rgb(w) for w in fixed.values()]
    tol = group.get('fixed_tolerance', 2500)
    rest = Counter({c: n for c, n in counts.items() if min((dist2(md_rgb(c), f) for f in fixed_rgb), default=tol + 1) > tol})
    k = len(group['free'])
    pts = [(md_rgb(c), n) for c, n in rest.items()]
    if len(pts) <= k:
        centres = [p for p, _ in pts]
    else:
        # farthest-point init from the most frequent colour, then weighted k-means
        centres = [max(pts, key=lambda p: p[1])[0]]
        while len(centres) < k:
            centres.append(max(pts, key=lambda p: p[1] * min(dist2(p[0], c) for c in centres))[0])
        for _ in range(20):
            sums = [[0, 0, 0, 0] for _ in centres]
            for p, n in pts:
                i = min(range(len(centres)), key=lambda i: dist2(p, centres[i]))
                for ch in range(3):
                    sums[i][ch] += p[ch] * n
                sums[i][3] += n
            centres = [tuple(s[ch] / s[3] for ch in range(3)) if s[3] else c for s, c in zip(sums, centres)]
    pal = dict(fixed)
    for slot, c in zip(group['free'], sorted(centres, key=sum)):
        pal[slot] = md_color(c)
    return pal


def to_indexed(im, pal):
    entries = [(s, md_rgb(w)) for s, w in pal.items()]
    cache = {}
    def idx(p):
        if p[3] < 128:
            return 0
        c = md_color(p)
        if c not in cache:
            cache[c] = min(entries, key=lambda e: dist2(md_rgb(c), e[1]))[0]
        return cache[c]
    return [[idx(im.getpixel((x, y))) for x in range(im.width)] for y in range(im.height)]


# ---------------------------------------------------------------- sprites

def chop(px, ax, ay, feet_y):
    """Split an indexed image into hardware sprites (max 4x4 tiles) covering exactly the non-empty
    8x8 tiles, trying every grid alignment. Returns (sprites, tile_bytes)."""
    h, w = len(px), len(px[0])
    ys = [y for y in range(h) if any(px[y])]
    xs = [x for x in range(w) if any(px[y][x] for y in range(h))]
    if not ys:
        sys.exit('empty frame')
    best = None
    for dx in range(8):
        for dy in range(8):
            r = _chop(px, min(xs) - dx, min(ys) - dy, max(xs), max(ys), ax, ay, feet_y)
            if best is None or (len(r[1]), len(r[0])) < (len(best[1]), len(best[0])):
                best = r
    return best


def _chop(px, x0, y0, x1, y1, ax, ay, feet_y):
    h, w = len(px), len(px[0])
    tw, th = (x1 - x0) // 8 + 1, (y1 - y0) // 8 + 1

    def tile(tx, ty):
        return [[px[y][x] if 0 <= y < h and 0 <= x < w else 0
                 for x in range(x0 + tx * 8, x0 + tx * 8 + 8)] for y in range(y0 + ty * 8, y0 + ty * 8 + 8)]

    free = [[any(any(r) for r in tile(tx, ty)) for tx in range(tw)] for ty in range(th)]
    sprites, data = [], bytearray()
    for ty in range(th):
        for tx in range(tw):
            if not free[ty][tx]:
                continue
            sw = 1
            while sw < 4 and tx + sw < tw and free[ty][tx + sw]:
                sw += 1
            sh = 1
            while sh < 4 and ty + sh < th and all(free[ty + sh][tx:tx + sw]):
                sh += 1
            for r in range(ty, ty + sh):
                for c in range(tx, tx + sw):
                    free[r][c] = False
            sprites.append({'x': x0 + tx * 8 - round(ax), 'y': y0 + ty * 8 - round(ay) + feet_y,
                            'size': ((sw - 1) << 2) | (sh - 1), 'pat': len(data) // 32})
            for c in range(tx, tx + sw):          # VDP sprites store tiles column-major
                for r in range(ty, ty + sh):
                    for line in tile(c, r):
                        data += bytes((line[i] << 4) | line[i + 1] for i in range(0, 8, 2))
    return sprites, bytes(data)


def metasprite(sprites, hurt, damage, mirrored):
    out = bytearray([len(sprites) - 1, hurt, damage])
    for s in sprites:
        w = ((s['size'] >> 2) & 3) + 1
        x = -s['x'] - w * 8 if mirrored else s['x']
        for v in (s['y'], x):
            if not -128 <= v <= 127:
                sys.exit(f'sprite offset {v} out of range; lower the scale')
        out += struct.pack('>bBHb', s['y'], s['size'], s['pat'] | (0x800 if mirrored else 0), x)
    return out


# ---------------------------------------------------------------- HUD

def tiles_from_indexed(px, tx, ty):
    """4bpp tile bytes for the 8x8 block at tile coords (tx, ty)."""
    out = bytearray()
    for r in range(8):
        row = px[ty * 8 + r][tx * 8:tx * 8 + 8]
        out += bytes((row[i] << 4) | row[i + 1] for i in range(0, 8, 2))
    return bytes(out)


def build_hud(rom, hud, palettes, root, alloc):
    """Replace the 16x16 hero portraits in the Nemesis-compressed HUD tile block."""
    block = bytearray(nemesis.decode(rom.d, hud['block'])[0])
    pal = palettes[hud['palette_group']]
    for p in hud['portraits']:
        # front-facing idle sprite, squared at the feet and scaled to 16x16
        im, _ = Pmd(os.path.join(root, p['pmd'])).frame(['Idle'], 0, 'down')
        im = im.crop(im.getbbox())
        side = max(im.size)
        square = Image.new('RGBA', (side, side))
        square.paste(im, ((side - im.width) // 2, side - im.height))
        im = square.resize((16, 16), Image.NEAREST)
        bg = Image.new('RGBA', im.size, md_rgb(pal[p['bg']]) + (255,))
        bg.alpha_composite(im)
        px = to_indexed(bg, pal)
        for k, (tx, ty) in enumerate(((0, 0), (1, 0), (0, 1), (1, 1))):   # nametable order: TL TR / BL BR
            t = p['tile'] + k
            block[t * 32:t * 32 + 32] = tiles_from_indexed(px, tx, ty)
    addr = alloc(nemesis.encode(bytes(block)))
    for ref in hud['refs']:
        assert rom.u16(ref - 2) == 0x41F9 and rom.u32(ref) == hud['block'], hex(ref)   # lea abs.l,a0
        rom.d[ref:ref + 4] = struct.pack('>I', addr)
    print(f'hud: {len(hud["portraits"])} portraits -> block {addr:#x}')


# ---------------------------------------------------------------- preloaded entities

def build_preloaded(rom, c, pal, presets, root, alloc):
    """Preloaded entities keep all frames in VRAM from one Nemesis block. Rebuild that block with the
    Pokémon's poses (shrinking the scale until it fits the VRAM budget) and give every animation
    frame a new metasprite; hit boxes come from the original metasprites."""
    if c.get('feet_y', 'auto') == 'auto':
        c = dict(c, feet_y=preloaded_feet(rom, c))
    orig_tiles = nemesis.decode(rom.d, c['block'])[0]
    keep = c.get('keep_tiles')
    budget = keep[0] if keep else c['budget']
    for scale in c.get('scales', [2, 1.75, 1.5, 1.25, 1]):
        pics = preloaded_pictures(rom, dict(c, scale=scale), presets, root)
        poses, blob = {}, bytearray()
        for key, variants in {k: v for k, v in pics.values()}.items():
            im, ax, ay = variants[0]
            sprites, data = chop(to_indexed(im, pal), ax, ay, c['feet_y'])
            poses[key] = (sprites, len(blob) // 32)
            blob += data
        if len(blob) // 32 <= budget:
            break
    else:
        sys.exit(f'{c["name"]}: does not fit {budget} tiles even at scale 1')
    if keep:
        blob = blob.ljust(keep[0] * 32, b'\0') + orig_tiles[keep[0] * 32:keep[1] * 32]
    packed = alloc(nemesis.encode(bytes(blob)))
    for ref in c['block_refs']:
        assert rom.u32(ref) == c['block'], hex(ref)
        rom.d[ref:ref + 4] = struct.pack('>I', packed)
    base = c.get('pattern_base', 0)
    n, done = c['animation_count'], set()
    for slot in range(2 * n):
        aaddr = rom.u32(c['animation_table'] + slot * 4)
        if aaddr in done or slot % n in c.get('skip_animations', []):
            continue
        done.add(aaddr)
        anim = read_preloaded_animation(rom, aaddr)
        for j, f in enumerate(anim['frames']):
            key = pics[(slot % n, j)][0]
            sprites, off = poses[key]
            shifted = [dict(sp, pat=sp['pat'] + off + base) for sp in sprites]
            mirrored = bool(f['ms']['sprites'][0]['pat'] & 0x800)
            ms = metasprite(shifted, f['ms']['hurt'], f['ms']['damage'], mirrored)
            rom.d[f['ptr_at']:f['ptr_at'] + 4] = struct.pack('>I', alloc(ms))
    used = sum(len(d) for d in []) or max(off + sum(tiles(sp['size']) for sp in sp_) for sp_, off in poses.values())
    print(f'{c["name"]:>10} -> {c["pokemon"]:<11} {len(poses)} poses at scale {scale}, {used}/{budget} tiles')


# ---------------------------------------------------------------- select screen

def build_select_screen(rom, sel, palette, root, alloc):
    """The select screen copies one raw pose per hero into VRAM ($44D8) and draws it with a
    metasprite from the table at $45F0. Its three palette lines are one shared palette at three
    brightness levels (front hero bright, others dimmed), so all starters use the hero palette."""
    for line, level in enumerate(sel['brightness']):
        for slot, w in palette.items():
            r, g, b_ = (min(7, round(((w >> s_) & 7) * level)) for s_ in (1, 5, 9))
            a_ = sel['palette'] + line * 32 + slot * 2
            rom.d[a_:a_ + 2] = struct.pack('>H', (b_ << 9) | (g << 5) | (r << 1))
    vram_tile = sel['vram_start']
    for h in sel['heroes']:
        im, (ax, ay) = Pmd(os.path.join(root, h['pmd'])).frame(['Idle'], 0, h.get('dir', 'down'))
        im = im.resize((im.width * sel['scale'], im.height * sel['scale']), Image.NEAREST)
        sprites, data = chop(to_indexed(im, palette), ax * sel['scale'], ay * sel['scale'], sel['feet_y'])
        n = len(data) // 32
        c = h['copy']
        vaddr = vram_tile * 32
        cmd = 0x40000000 | ((vaddr & 0x3FFF) << 16) | (vaddr >> 14)
        assert rom.u16(c - 2) == 0x2E3C and rom.u16(c + 4) == 0x4DF9 and rom.u16(c + 10) == 0x3C3C, hex(c)
        rom.d[c:c + 4] = struct.pack('>I', cmd)
        rom.d[c + 6:c + 10] = struct.pack('>I', alloc(data))
        rom.d[c + 12:c + 14] = struct.pack('>H', n * 16)
        t = h['table']
        rom.d[t:t + 4] = struct.pack('>I', alloc(metasprite(sprites, 0, 0, False)))
        rom.d[t + 4:t + 6] = struct.pack('>H', vram_tile)
        print(f'select: {h["pmd"].split("/")[-1]} {n} tiles at VRAM tile {vram_tile:#x}')
        vram_tile += n
    assert vram_tile <= sel['vram_end'], 'select screen sprites overflow free VRAM'


# ---------------------------------------------------------------- gameplay patches

# On a hit: health above 1 drops to 1, otherwise to 0. Leaves the CCR as the original
# `sub.b d3,$64(a0)` would for the following bgt/bhi (alive = Z clear, N clear, C clear).
HP_LOGIC = bytes.fromhex('0c2800010064'   # cmpi.b #1,$64(a0)
                         '6308'           # bls.s  .kill
                         '117c00010064'   # move.b #1,$64(a0)
                         '4e75'           # rts
                         '42280064'       # .kill: clr.b $64(a0)
                         '4e75')          # rts
SUB = bytes.fromhex('97280064')            # sub.b d3,$64(a0)
HP_SITES = (0xdcc6, 0xdd00, 0xeea0, 0xeec8, 0xf3a8, 0x1086a, 0x10892, 0x11530, 0x11552, 0x11f54, 0x11f76)
TRAMPOLINE = 0x140d0                       # inside a 370-byte run of $FF padding, within bsr.w reach


def two_hit_kills(rom, alloc):
    """Every enemy dies on its second hit. Only the 4-byte `sub.b d3,$64(a0)` at each damage site
    (found by disassembling) is replaced, by a same-size `bsr.w` to a jmp trampoline, so every
    instruction boundary the original code may branch to stays intact (e.g. $F39A -> $F3A8)."""
    hook = alloc(HP_LOGIC)
    assert rom.d[TRAMPOLINE - 2:TRAMPOLINE + 8] == b'\xff' * 10, 'trampoline area not free'
    rom.d[TRAMPOLINE:TRAMPOLINE + 6] = b'\x4e\xf9' + struct.pack('>I', hook)       # jmp hook
    for site in HP_SITES:
        assert rom.d[site:site + 4] == SUB, f'{site:#x}: unexpected bytes'
        disp = TRAMPOLINE - (site + 2)
        assert -0x8000 <= disp < 0x8000
        rom.d[site:site + 4] = struct.pack('>Hh', 0x6100, disp)                     # bsr.w trampoline
    print(f'patch: two-hit kills at {len(HP_SITES)} damage sites')


# ---------------------------------------------------------------- assembler

VASM = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.tools', 'vasm', 'vasmm68k_mot')


def assemble(src, org):
    with tempfile.TemporaryDirectory() as d:
        open(f'{d}/a.s', 'w').write(f' org ${org:x}\n' + src)
        subprocess.run([VASM, '-quiet', '-no-opt', '-Fbin', '-o', f'{d}/a.bin', f'{d}/a.s'], check=True)
        return open(f'{d}/a.bin', 'rb').read()


def place(src, alloc):
    """Assemble at the address alloc will hand out (size from a first pass at org 0)."""
    size = len(assemble(src, 0))
    addr = alloc(b'\0' * size)
    code = assemble(src, addr)
    assert len(code) == size
    return addr, code


# ---------------------------------------------------------------- cries

def build_cries(rom, cfg, chars, root, alloc):
    """Each Pokémon enemy cries when hit (short, higher) and when knocked out (full cry).
    KO: the 7 `jsr $358C/$3594` scream loaders in enemy code go through a dispatcher keyed on the
    entity's animation table. Hit: the global sound routine $3652 is hooked; hit SFX $91-$94 from
    an enemy entity whose type is a Pokémon play its hit cry instead (enemy hits use $91-$94)."""
    cal = cfg['calibration']
    rows = []
    for c in chars:
        if c['name'] not in cfg['pokemon']:
            continue
        path = os.path.join(root, cfg['pokemon'][c['name']])
        death, secs = cries.cry(path, cfg['death_pitch'], cal)
        hit_samples = cries.load(path, cries.rate(cfg['hit_pitch'], cal) * cfg.get('hit_speed', 1.0))
        hit, _ = cries.cry(path, cfg['hit_pitch'], cal, speed=cfg.get('hit_speed', 1.0))
        cut = int(cfg['hit_seconds'] * cries.rate(cfg['hit_pitch'], cal)) // 2
        hit = hit[:8 + cut].ljust(cries.BLOCK, b'\x88')
        hit = len(hit[8:8 + cut]).to_bytes(2, 'little') + hit[2:]
        rows.append((c['animation_table'], alloc(death), alloc(hit)))
        print(f'cry: {c["pokemon"]:<10} KO {secs:.2f}s, hit {cfg["hit_seconds"]:.2f}s')
    table = ''.join(f' dc.l ${t:x},${d:x},${h:x}\n' for t, d, h in rows) + ' dc.l 0\n'

    # KO dispatcher: d1 = default block (Sega's scream), d7 = caller's pitch
    ko_src = f"""
dispatch:
 move.l a1,-(sp)
 lea table(pc),a1
.loop:
 move.l (a1)+,d0
 beq.s .done
 cmp.l $e(a0),d0
 beq.s .found
 addq.l #8,a1
 bra.s .loop
.found:
 move.l (a1),d1
 moveq #${cfg['death_pitch']:x},d7
.done:
 move.l (sp)+,a1
 jmp $359a
table:
{table}"""
    ko, code = place(ko_src, alloc)
    rom.d[ko:ko + len(code)] = code
    for site, default in cfg['death_sites'].items():
        site = int(site)
        assert rom.u16(site) == 0x4EB9 and rom.u32(site + 2) in (0x358C, 0x3594), hex(site)
        stub, code = place(f' move.l #${default:x},d1\n jmp ${ko:x}\n', alloc)
        rom.d[stub:stub + len(code)] = code
        rom.d[site + 2:site + 6] = struct.pack('>I', stub)

    # hit hook at the head of the global sound routine $3652
    assert rom.d[0x3652:0x365a] == bytes.fromhex('007c070048e78000'), 'unexpected $3652 entry'
    hit_src = f"""
 cmpi.b #$91,d7
 blo.s .orig
 cmpi.b #$94,d7
 bhi.s .orig
 movem.l d0-d1/d7/a1/a5-a6,-(sp)        ; the sample loader clobbers these; sfx callers don't expect it
 move.l a0,d0
 cmpi.l #$ffffd100,d0                    ; enemy entity slots (sign-extended $D100-$EFFF)
 blo.s .none
 cmpi.l #$fffff000,d0
 bhs.s .none
 lea table(pc),a1
.loop:
 move.l (a1)+,d0
 beq.s .none
 cmp.l $e(a0),d0
 beq.s .found
 addq.l #8,a1
 bra.s .loop
.found:
 move.l 4(a1),d1
 moveq #${cfg['hit_pitch']:x},d7
 jsr $359a
 movem.l (sp)+,d0-d1/d7/a1/a5-a6
 rts                                     ; cry replaces the hit sfx
.none:
 movem.l (sp)+,d0-d1/d7/a1/a5-a6
.orig:
 ori.w #$700,sr
 movem.l d0,-(sp)
 jmp $365a
table:
{table}"""
    hook, code = place(hit_src, alloc)
    rom.d[hook:hook + len(code)] = code
    rom.d[0x3652:0x365a] = b'\x4e\xf9' + struct.pack('>I', hook) + b'\x4e\x71'
    print(f'cries: KO dispatcher {ko:#x}, hit hook {hook:#x}, {len(cfg["death_sites"])} KO sites')


# ---------------------------------------------------------------- build

def main(cfg_path, src, dst):
    cfg = json.load(open(cfg_path))
    root = os.path.dirname(os.path.abspath(cfg_path))
    rom = Rom(open(src, 'rb').read())
    orig = Rom(bytes(rom.d))
    rom.d += b'\xff' * (0x100000 - len(rom.d))
    free = 0x80000

    def alloc(blob):
        nonlocal free
        free += free & 1
        addr = free
        rom.d[addr:addr + len(blob)] = blob
        free += len(blob)
        return addr

    chars = [c for c in cfg['characters'] if c.get('enabled', True)]
    pictures = {c['name']: character_pictures(rom, c, cfg.get('presets', {}), root) for c in chars}

    palettes = {}
    for gname, group in cfg['palette_groups'].items():
        imgs = [v[1][0][0] for c in chars if c['palette_group'] == gname for v in pictures[c['name']].values()]
        if imgs:
            palettes[gname] = build_group_palette(rom, group, imgs)
            for addr in group['palettes']:
                assert rom.u8(addr + 1) == 15, hex(addr)
                for slot in group['free'] + [int(k) for k in group.get('fixed_values', {})]:
                    if slot not in palettes[gname]:
                        continue
                    rom.d[addr + 2 + slot * 2:addr + 4 + slot * 2] = struct.pack('>H', palettes[gname][slot])

    for gname, group in cfg['palette_groups'].items():
        for colours in group.get('copies', []):     # raw 16-colour copies, e.g. reloaded after magic
            for slot in group['free']:
                if slot in palettes.get(gname, {}):
                    assert orig.u16(colours + slot * 2) == orig.u16(group['palettes'][0] + 2 + slot * 2), hex(colours)
                    rom.d[colours + slot * 2:colours + slot * 2 + 2] = struct.pack('>H', palettes[gname][slot])

    for c in chars:
        if c.get('kind') == 'preloaded':
            build_preloaded(rom, c, palettes[c['palette_group']], cfg.get('presets', {}), root, alloc)
            continue
        pal, limit = palettes[c['palette_group']], c['max_tiles']
        blob, layouts, uniq, tile_ids = bytearray(), {}, {}, {}
        for d, (key, variants) in sorted(pictures[c['name']].items()):
            if key not in uniq:
                for im, ax, ay in variants:
                    sprites, data = chop(to_indexed(im, pal), ax, ay, c['feet_y'])
                    n = len(data) // 32
                    if n <= limit and len(sprites) <= 20:
                        break
                if n > limit:
                    sys.exit(f'{c["name"]}: picture {d} needs {n} tiles (max {limit}); lower the scale')
                ids = []
                for t in range(n):
                    tb = data[t * 32:t * 32 + 32]
                    if tb not in tile_ids:
                        tile_ids[tb] = len(blob) // 32
                        blob += tb
                    ids.append(tile_ids[tb])
                uniq[key] = (sprites, ids)
            layouts[d] = uniq[key]
        if len(blob) > 0xFFFF:
            sys.exit(f'{c["name"]}: tile data exceeds the 64 KiB DMA offset range')
        src = c.get('tile_source', {'mode': 'rom'})
        if src['mode'] == 'rom':
            tile_base = alloc(bytes(blob))
            for ref in c['tile_base_refs']:
                assert rom.u32(ref) == c['tile_base'], f'{c["name"]}: {ref:#x}'
                rom.d[ref:ref + 4] = struct.pack('>I', tile_base)
        else:   # Nemesis-compressed blob the game unpacks into RAM at stage start
            assert len(blob) <= src['max_bytes'], f'{c["name"]}: {len(blob)} bytes of tiles, RAM buffer holds {src["max_bytes"]}'
            packed = alloc(nemesis.encode(bytes(blob)))
            for ref in src['refs']:
                assert rom.u16(ref - 2) == 0x41F9 and rom.u32(ref) == src['block'], hex(ref)
                rom.d[ref:ref + 4] = struct.pack('>I', packed)
        for d, (_, ids) in layouts.items():
            runs, start = [], 0
            for k in range(1, len(ids) + 1):
                if k == len(ids) or ids[k] != ids[k - 1] + 1:
                    runs.append(struct.pack('>hH', (k - start) * 16, ids[start] * 32))
                    start = k
            ptr = c['dma_table'] + d * 4
            rom.d[ptr:ptr + 4] = struct.pack('>I', alloc(b''.join(runs) + struct.pack('>h', -1)))

        half, done = c['animation_count'], set()
        for a in range(half * 2):
            aaddr = rom.u32(c['animation_table'] + a * 4)
            if aaddr in done:
                continue
            done.add(aaddr)
            anim = read_dma_animation(rom, aaddr)
            for i, f in enumerate(anim['frames']):
                if f['dma'] not in layouts:
                    sys.exit(f'{c["name"]}: animation {a} uses picture {f["dma"]}, which has no mapping')
                mirrored = bool(f['ms']['sprites'][0]['pat'] & 0x800)
                frame = bytes([f['damage'], f['dma']]) + metasprite(layouts[f['dma']][0], f['ms']['hurt'], f['ms']['damage'], mirrored)
                rom.d[aaddr + 4 + i * 4:aaddr + 8 + i * 4] = struct.pack('>I', alloc(frame))
        print(f'{c["name"]:>10} -> {c["pokemon"]:<11} {len(layouts)} pictures ({len(uniq)} unique), '
              f'{len(blob) // 32} tiles, max {max(len(l[1]) for l in layouts.values())}/{limit} per frame')

    depth = cfg.get('patches', {}).get('hit_depth_tolerance')
    if depth:
        assert rom.u16(0xBF48) == 0x7408, 'unexpected closeness code'   # moveq #8,d2
        rom.d[0xBF49] = depth
        print(f'patch: hit depth tolerance 8 -> {depth}px')

    if cfg.get('patches', {}).get('two_hit_kills'):
        two_hit_kills(rom, alloc)

    if 'select_screen' in cfg:
        build_select_screen(rom, cfg['select_screen'], palettes['heroes'], root, alloc)

    if 'cries' in cfg:
        build_cries(rom, cfg['cries'], chars, root, alloc)

    if 'hud' in cfg:
        build_hud(rom, cfg['hud'], palettes, root, alloc)

    for g, pal in palettes.items():
        print(f'palette {g}: ' + ' '.join(f'{s}:{pal[s]:03x}' for s in sorted(pal)))
    rom.d[0x1A4:0x1A8] = struct.pack('>I', len(rom.d) - 1)
    rom.d[0x18E:0x190] = struct.pack('>H', sum(struct.unpack_from(f'>{(len(rom.d) - 0x200) // 2}H', rom.d, 0x200)) & 0xFFFF)
    open(dst, 'wb').write(rom.d)
    print(f'data {0x80000:#x}-{free:#x} -> {dst}')


if __name__ == '__main__':
    main(*sys.argv[1:4])
