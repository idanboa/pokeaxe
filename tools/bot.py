"""Scripted Golden Axe player on top of emu.py: fight through a stage, optionally favouring dash attacks.

Entity layout per jvisser/golden-axe-32x-edition doc/entity.md: slots of 0x80 bytes at $FFD000
(players 0-1, map entities 2-9), x at $1C and base y at $20 (16.16 fixed point), id at $00.
"""
import struct

ENTITY_BASE = 0xFFD000


def entities(emu):
    raw = emu.ram(ENTITY_BASE, 0x80 * 10)
    out = []
    for i in range(10):
        e = raw[i * 0x80:(i + 1) * 0x80]
        out.append({'slot': i, 'id': e[0], 'x': struct.unpack_from('>h', e, 0x1C)[0],
                    'y': struct.unpack_from('>h', e, 0x20)[0], 'hp': e[0x64], 'raw': e})
    return out


def start_game(emu, hero_moves=0):
    """Boot -> title -> arcade -> select (hero_moves presses of RIGHT) -> stage 1."""
    emu.run(360)
    for _ in range(3):
        emu.press({'START'}, 4, 60)
    for _ in range(hero_moves):
        emu.press({'RIGHT'}, 4, 20)
    emu.press({'START'}, 4, 240)


def step(emu, dash=True):
    """One decision (about 1/6 s). Returns the target enemy or None."""
    ents = entities(emu)
    me = ents[0]
    foes = [e for e in ents[2:] if e['id'] and e['hp'] > 0]
    if not foes:
        emu.run(8, {'RIGHT'})
        emu.press({'C'}, 2, 2)          # also advances dialogue
        return None
    t = min(foes, key=lambda e: abs(e['x'] - me['x']) + 2 * abs(e['y'] - me['y']))
    dx, dy = t['x'] - me['x'], t['y'] - me['y']
    horiz = 'RIGHT' if dx > 0 else 'LEFT'
    if abs(dy) > 3:
        emu.run(6, {'DOWN' if dy > 0 else 'UP'} | ({horiz} if abs(dx) > 40 else set()))
    elif dash and abs(dx) > 70:
        # double tap to run, then attack when close
        emu.run(3, {horiz}); emu.run(3); emu.run(14, {horiz})
        emu.run(4, {horiz, 'B'}); emu.run(8)
    elif abs(dx) > 34:
        emu.run(6, {horiz})
    else:
        emu.run(3, {horiz} if (dx > 0) != (me['raw'][0x45] & 1 == 0) else set())
        emu.press({'B'}, 3, 5)
    return t
