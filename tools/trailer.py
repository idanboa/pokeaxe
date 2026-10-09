"""Record a PokeAxe trailer from real emulated gameplay.

usage: python3 -E tools/trailer.py out/PokeAxe.md out/PokeAxe-trailer.mp4
"""
import os, struct, subprocess, sys, wave
import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from emu import Emu
import bot

W, H, FPS = 1920, 1080, 60000 / 1001
SCALE = 4
FONT = '/System/Library/Fonts/Supplemental/Impact.ttf'
YELLOW, RED, WHITE = (255, 214, 0), (200, 30, 30), (255, 255, 255)


def font(size):
    return ImageFont.truetype(FONT, size)


def outlined(d, xy, text, size, fill, outline=(0, 0, 0), width=6, anchor='mm'):
    d.text(xy, text, font=font(size), fill=fill, stroke_width=width, stroke_fill=outline, anchor=anchor)


class Trailer:
    def __init__(self, rom, out):
        self.rom, self.out = rom, out
        self.tmp = out + '.video.mp4'
        self.wav = wave.open(out + '.wav', 'wb')
        self.wav.setnchannels(2); self.wav.setsampwidth(2); self.wav.setframerate(44100)
        self.ff = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error',
                                    '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', '60000/1001', '-i', '-',
                                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-pix_fmt', 'yuv420p', self.tmp],
                                   stdin=subprocess.PIPE)
        self.caption = None
        self.samples_per_frame = 44100 / FPS
        self.audio_debt = 0.0

    # -- output
    def put(self, img, audio=b''):
        self.ff.stdin.write(img.tobytes())
        # keep audio exactly in step with video: pad or trim to this frame's share
        self.audio_debt += self.samples_per_frame
        want = int(self.audio_debt)
        self.audio_debt -= want
        audio = audio[:want * 4].ljust(want * 4, b'\0')
        self.wav.writeframes(audio)

    def compose(self, game):
        canvas = Image.new('RGB', (W, H))
        g = game.resize((game.width * SCALE, game.height * SCALE), Image.NEAREST)
        canvas.paste(g, ((W - g.width) // 2, (H - g.height) // 2))
        if self.caption:
            d = ImageDraw.Draw(canvas)
            outlined(d, (W // 2, H - 44), self.caption, 58, YELLOW)
        return canvas

    def card(self, seconds, title, subtitle=None, small=None):
        img = Image.new('RGB', (W, H), (8, 8, 16))
        d = ImageDraw.Draw(img)
        outlined(d, (W // 2, H // 2 - 40), title, 190, YELLOW, RED, 12)
        if subtitle:
            outlined(d, (W // 2, H // 2 + 110), subtitle, 60, WHITE, (0, 0, 0), 4)
        if small:
            d.text((W // 2, H - 80), small, font=font(34), fill=(170, 170, 190), anchor='mm')
        for _ in range(int(seconds * FPS)):
            self.put(img)

    # -- gameplay
    def attach(self, emu):
        def rec(e):
            audio = bytes(e.audio)
            e.audio.clear()
            self.put(self.compose(e.frame()), audio)
        emu.audio.clear()
        emu.on_frame = rec

    def detach(self, emu):
        emu.on_frame = None

    def close(self):
        self.ff.stdin.close(); self.ff.wait(); self.wav.close()
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-i', self.tmp, '-i', self.out + '.wav',
                        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', self.out], check=True)
        os.remove(self.tmp); os.remove(self.out + '.wav')


SELECT = {'Bulbasaur': [], 'Charmander': ['LEFT', 'LEFT'], 'Squirtle': ['RIGHT', 'RIGHT']}


def to_select(rom):
    e = Emu(rom)
    e.run(360)
    for _ in range(3):
        e.press({'START'}, 4, 60)
    e.run(60)
    return e


def start_as(rom, hero):
    e = to_select(rom)
    for k in SELECT[hero]:
        e.press({k}, 6, 40)
    e.press({'START'}, 4, 240)
    return e


def start_level(rom, hero, level):
    """Start the game in a given stage (0-7) by setting the level word at $FFFE2C on the select screen."""
    e = to_select(rom)
    for k in SELECT[hero]:
        e.press({k}, 6, 40)
    e.poke(0xFFFE2C, bytes([0, level]))
    e.press({'START'}, 4, 300)
    return e


def on_screen(e, tables):
    for x in bot.entities(e)[2:]:
        if x['id'] and struct.unpack_from('>I', x['raw'], 0x0E)[0] in tables:
            sx = struct.unpack_from('>h', x['raw'], 0x1C)[0] - 128
            if 40 < sx < 280:
                return True
    return False


def walk_to_fight(e, max_steps=600):
    for _ in range(max_steps):
        ents = bot.entities(e)
        foes = [x for x in ents[2:] if x['id'] and x['hp'] > 0]
        if foes and min(abs(f['x'] - ents[0]['x']) for f in foes) < 140:
            return True
        e.run(8, {'RIGHT'})
        e.press({'C'}, 2, 2)
    return False


POKEMON_TABLES = {0x43656, 0x71F72, 0x790D2, 0x3ED06, 0x737AE, 0x74192, 0x7C718, 0x4086A, 0x41B16}


def pokemon_foes(e):
    return sum(1 for x in bot.entities(e)[2:]
               if x['id'] and x['hp'] > 0 and struct.unpack_from('>I', x['raw'], 0x0E)[0] in POKEMON_TABLES)


def invulnerable(e):
    e.poke(0xFFFE7C, b'\x03\x03')      # health/lives bytes (found by RAM diff): keep the bot alive


def fight(t, e, seconds, dash_every=3):
    t.attach(e)
    target = e.frames + int(seconds * FPS)
    i = 0
    while e.frames < target:
        invulnerable(e)
        bot.step(e, dash=(i % dash_every == 0))
        i += 1
    t.detach(e)


def main(rom, out):
    t = Trailer(rom, out)

    t.card(2.5, 'POKÉAXE', 'Golden Axe  ×  Pokémon', 'A Sega Mega Drive mod')

    # title screen
    e = Emu(rom)
    e.run(560)
    t.caption = None
    t.attach(e); e.run(int(3.5 * FPS)); t.detach(e)

    # select screen, cycling the starters
    e = to_select(rom)
    t.caption = 'CHOOSE YOUR STARTER'
    t.attach(e)
    e.run(50)
    for k in ('RIGHT', 'RIGHT', 'LEFT', 'LEFT', 'LEFT', 'LEFT', 'RIGHT', 'RIGHT'):
        e.press({k}, 6, 34)
    t.detach(e)

    for hero, move in (('Bulbasaur', 'RAZOR LEAF'), ('Charmander', 'EMBER'), ('Squirtle', 'BUBBLE')):
        e = start_as(rom, hero)
        walk_to_fight(e)
        t.caption = f'{hero.upper()}  —  {move}'
        fight(t, e, 6.5)
        # magic, cast while enemies are close
        for _ in range(200):
            if pokemon_foes(e) >= 1:
                break
            bot.step(e)
        t.caption = f'{hero.upper()}  —  MAGIC'
        t.attach(e)
        e.run(6, {'A'})
        e.run(int(3.4 * FPS))
        t.detach(e)

    # enemies montage: start once two or more Pokémon foes are on screen
    e = start_as(rom, 'Charmander')
    walk_to_fight(e)
    for i in range(500):
        if i > 60 and pokemon_foes(e) >= 2:
            break
        bot.step(e, dash=True)
    t.caption = 'PIKACHU  •  MACHOP  •  JYNX  —  EACH WITH ITS OWN CRY'
    fight(t, e, 9, dash_every=2)

    # later stages: jump straight to a stage, record once the featured Pokémon is on screen
    for level, hero, tables, caption in ((2, 'Bulbasaur', {0x41B16}, 'STAGE 3  —  CHARIZARD'),
                                         (0, 'Charmander', {0x4086A}, 'RIDE RHYDON'),
                                         (0, 'Squirtle', {0x737AE}, 'MACHAMP  —  STAGE 1 BOSS'),
                                         (4, 'Charmander', {0x7C718}, 'SCIZOR  —  THE ARMOURED KNIGHT'),
                                         (5, 'Bulbasaur', {0x74192}, 'TYRANITAR  —  DEATH ADDER'),
                                         (7, 'Squirtle', {0x74192}, 'FINAL BOSS  —  DEATH BRINGER')):
        e = start_level(rom, hero, level)
        for i in range(1500):
            if on_screen(e, tables):
                break
            invulnerable(e)
            bot.step(e, dash=(i % 3 == 0))
        t.caption = caption
        fight(t, e, 5.5)

    t.caption = None
    t.card(3.5, 'POKÉAXE', '8 stages  •  12 Pokémon foes  •  each with its own cry', 'Sprites: PMD SpriteCollab  •  Golden Axe © SEGA  •  Pokémon © Nintendo / Game Freak')
    t.close()
    print('wrote', out)


if __name__ == '__main__':
    main(*sys.argv[1:3])
