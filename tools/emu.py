"""Minimal libretro frontend for Genesis Plus GX, driven from Python.

    emu = Emu('out/PokeAxe.md')
    emu.run(60)                                # advance frames
    emu.run(10, buttons={'B'})                 # hold buttons (Golden Axe: B attack, C jump, A magic)
    emu.frame()                                # last frame as a PIL image
    emu.ram(0xFFD000, 0x80)                    # 68k work RAM
    emu.load_state(path) / emu.save_state()

Mega Drive buttons map to RetroPad ids per Genesis Plus GX defaults (Y=A, B=B, A=C).
"""
import ctypes as C
import os
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, '..', '.tools', 'gpgx', 'genesis_plus_gx_libretro.dylib')

PAD = {'B': 0, 'A': 1, 'MODE': 2, 'START': 3, 'UP': 4, 'DOWN': 5, 'LEFT': 6, 'RIGHT': 7, 'C': 8}

ENV_GET_CAN_DUPE, ENV_SET_PIXEL_FORMAT = 3, 10
ENV_GET_SYSTEM_DIRECTORY, ENV_GET_SAVE_DIRECTORY = 9, 31
ENV_GET_VARIABLE, ENV_GET_VARIABLE_UPDATE = 15, 17
PIXEL_0RGB1555, PIXEL_XRGB8888, PIXEL_RGB565 = 0, 1, 2


class GameInfo(C.Structure):
    _fields_ = [('path', C.c_char_p), ('data', C.c_void_p), ('size', C.c_size_t), ('meta', C.c_char_p)]


class Variable(C.Structure):
    _fields_ = [('key', C.c_char_p), ('value', C.c_char_p)]


ENV_CB = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
VIDEO_CB = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
AUDIO_CB = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
AUDIO_BATCH_CB = C.CFUNCTYPE(C.c_size_t, C.POINTER(C.c_int16), C.c_size_t)
POLL_CB = C.CFUNCTYPE(None)
STATE_CB = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)


class Emu:
    def __init__(self, rom, options=None):
        self.lib = C.CDLL(CORE)
        self.fmt = PIXEL_RGB565
        self.buttons = set()
        self.audio = bytearray()
        self.last = None
        # strings handed to the core must outlive the call, so keep them in C buffers
        self.options = {k.encode(): C.create_string_buffer(v.encode()) for k, v in (options or {}).items()}
        self._keep = []
        self.sysdir = C.create_string_buffer(os.path.abspath(os.path.join(HERE, '..', '.tools')).encode())

        def env(cmd, data):
            if cmd == ENV_SET_PIXEL_FORMAT:
                self.fmt = C.cast(data, C.POINTER(C.c_int))[0]
                return True
            if cmd == ENV_GET_CAN_DUPE:
                C.cast(data, C.POINTER(C.c_bool))[0] = True
                return True
            if cmd in (ENV_GET_SYSTEM_DIRECTORY, ENV_GET_SAVE_DIRECTORY):
                C.cast(data, C.POINTER(C.c_void_p))[0] = C.addressof(self.sysdir)
                return True
            if cmd == ENV_GET_VARIABLE:
                v = C.cast(data, C.POINTER(Variable))
                key = v[0].key
                if key in self.options:
                    C.cast(C.c_void_p(data + C.sizeof(C.c_void_p)), C.POINTER(C.c_void_p))[0] = C.addressof(self.options[key])
                    return True
                return False
            if cmd == ENV_GET_VARIABLE_UPDATE:
                C.cast(data, C.POINTER(C.c_bool))[0] = False
                return True
            return False

        def video(data, w, h, pitch):
            if data:
                self.last = (C.string_at(data, pitch * h), w, h, pitch)

        def audio(l, r):
            self.audio += l.to_bytes(2, 'little', signed=True) + r.to_bytes(2, 'little', signed=True)

        def audio_batch(data, frames):
            self.audio += C.string_at(data, frames * 4)
            return frames

        def state(port, device, index, bid):
            if port != 0 or device != 1:
                return 0
            return 1 if any(PAD[b] == bid for b in self.buttons) else 0

        cbs = [ENV_CB(env), VIDEO_CB(video), AUDIO_CB(audio), AUDIO_BATCH_CB(audio_batch), POLL_CB(lambda: None), STATE_CB(state)]
        self._keep += cbs
        L = self.lib
        L.retro_set_environment(cbs[0])
        L.retro_init()
        L.retro_set_video_refresh(cbs[1])
        L.retro_set_audio_sample(cbs[2])
        L.retro_set_audio_sample_batch(cbs[3])
        L.retro_set_input_poll(cbs[4])
        L.retro_set_input_state(cbs[5])
        self.rom = open(rom, 'rb').read()
        self._rombuf = C.create_string_buffer(self.rom, len(self.rom))
        info = GameInfo(os.path.abspath(rom).encode(), C.cast(self._rombuf, C.c_void_p), len(self.rom), None)
        L.retro_load_game.restype = C.c_bool
        assert L.retro_load_game(C.byref(info)), 'load failed'
        L.retro_serialize_size.restype = C.c_size_t
        L.retro_get_memory_data.restype = C.c_void_p
        L.retro_get_memory_size.restype = C.c_size_t
        self.frames = 0
        self.on_frame = None            # callback(emu) after every emulated frame, e.g. a recorder

        class Geometry(C.Structure):
            _fields_ = [('bw', C.c_uint), ('bh', C.c_uint), ('mw', C.c_uint), ('mh', C.c_uint), ('aspect', C.c_float)]

        class Timing(C.Structure):
            _fields_ = [('fps', C.c_double), ('sample_rate', C.c_double)]

        class AV(C.Structure):
            _fields_ = [('geometry', Geometry), ('timing', Timing)]
        av = AV()
        L.retro_get_system_av_info(C.byref(av))
        self.fps, self.sample_rate = av.timing.fps, av.timing.sample_rate

    def run(self, n=1, buttons=()):
        self.buttons = set(buttons)
        for _ in range(n):
            self.lib.retro_run()
            self.frames += 1
            if self.on_frame:
                self.on_frame(self)
        self.buttons = set()

    def press(self, buttons, hold=4, release=4):
        self.run(hold, buttons)
        self.run(release)

    def frame(self):
        data, w, h, pitch = self.last
        if self.fmt == PIXEL_XRGB8888:
            return Image.frombuffer('RGBX', (w, h), data, 'raw', 'BGRX', pitch, 1).convert('RGB')
        return Image.frombuffer('RGB', (w, h), data, 'raw', 'BGR;16', pitch, 1)

    def ram(self, addr=0xFF0000, size=0x10000):
        """68k work RAM (0xFF0000-0xFFFFFF)."""
        p = self.lib.retro_get_memory_data(2)
        n = self.lib.retro_get_memory_size(2)
        buf = C.string_at(p, n)
        off = addr & 0xFFFF
        # Genesis Plus GX keeps 68k RAM byte-swapped per word on little-endian hosts
        raw = buf[off & ~1:(off + size + 1) & ~1 | 0]
        sw = bytes(raw[i ^ 1] for i in range(len(raw)))
        return sw[off & 1:(off & 1) + size]

    def poke(self, addr, data):
        """Write bytes into 68k work RAM."""
        p = self.lib.retro_get_memory_data(2)
        for i, b in enumerate(data):
            a = ((addr + i) & 0xFFFF) ^ 1
            C.c_uint8.from_address(p + a).value = b

    def save_state(self):
        n = self.lib.retro_serialize_size()
        buf = C.create_string_buffer(n)
        assert self.lib.retro_serialize(buf, C.c_size_t(n))
        return buf.raw

    def load_state(self, data):
        if isinstance(data, str):
            data = open(data, 'rb').read()
        buf = C.create_string_buffer(data, len(data))
        assert self.lib.retro_unserialize(buf, C.c_size_t(len(data))), 'state load failed'
