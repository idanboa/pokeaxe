# Instructions for coding agents

PokéAxe patches **Golden Axe (World) (Rev A)** for the Sega Mega Drive so its characters are Pokémon. Everything is
generated: `tools/build.py` reads the original ROM plus downloaded sprites/cries and writes a new 1 MiB ROM; the
release artefact is a BPS patch. Read `README.md` first for the player-facing view.

## Hard rules

- **Never commit or upload ROMs, ROM dumps, extracted game data, sprites or cries.** `.gitignore` is a whitelist
  (only `README.md`, `CREDITS.md`, `LICENSE`, `AGENTS.md`, `CLAUDE.md`, `tools/`, `docs/`, `patch/*.bps`). If you add a
  new top-level file that belongs in the repo, whitelist it explicitly; never loosen the rule with a broad pattern.
- Never add links or hints pointing to ROM download sites.
- The base ROM must be Rev A: CRC32 `665D7DF9`, SHA-1 `2CE17105CA916FBBE3AC9AE3A2086E66B07996DD`. All addresses
  below are for that ROM.
- Keep the project non-commercial (sprites are CC BY-NC 4.0). Update `CREDITS.md` when adding a Pokémon.

## Layout

| Path | What |
|---|---|
| `tools/mod.json` | The whole mod as data: palette groups, presets, characters, select screen, HUD, cries, patches |
| `tools/build.py` | Builder. Sections: pictures, palettes, sprites (chop), preloaded entities, select screen, gameplay patches, assembler, cries, HUD, main |
| `tools/garom.py` | Readers for DMA animations, metasprites and preloaded animations |
| `tools/nemesis.py` | Nemesis codec (encoder is valid but unoptimised: escape codes only) |
| `tools/cries.py` | OGG → 4-bit DPCM sample blocks for the Z80 driver |
| `tools/bps.py` | BPS create/apply |
| `tools/emu.py` | ctypes libretro frontend for Genesis Plus GX: frames, audio, RAM read/write (`poke`), save states |
| `tools/bot.py` | Scripted player (reads entity RAM, walks/attacks/dashes) |
| `tools/trailer.py` | Scripted trailer recorder (1080p + game audio via ffmpeg) |
| `tools/verify.py` | Re-exports DMA characters from a built ROM with the 32X project's DataVis (needs `ref/ga32x` + a JDK) |
| `tools/mdstate.py` | Reads VRAM/CRAM/planes from OpenEmu (GPGX 1.7.6) save states |

Local-only (ignored) directories: `assets/` (from `tools/fetch_assets.sh`), `.tools/` (vasm, Genesis Plus GX core,
optional JDK/Maven), `ref/ga32x` (clone of jvisser/golden-axe-32x-edition, its `doc/` is the best format reference),
`out/` (builds, trailer).

## Build and verify

```sh
tools/fetch_assets.sh
python3 tools/build.py tools/mod.json <GoldenAxeRevA.md> out/PokeAxe.md
```

The build exits with a message on any budget overflow or unexpected original bytes (every patch asserts what it
overwrites). Before calling a change done:

1. Build succeeds; every character fits its tile budget.
2. **Play it in the harness**, not just in previews. The pattern used throughout:
   ```python
   import sys; sys.path.insert(0, 'tools')
   import trailer, bot
   e = trailer.start_level('out/PokeAxe.md', 'Bulbasaur', level)   # level 0-7
   for i in range(1500):
       trailer.invulnerable(e)            # optional: keep the bot alive
       bot.step(e, dash=(i % 3 == 0))
       # detect freezes: identical frames for ~40 steps; save e.save_state() for debugging
   ```
   Run all three heroes and the affected stages. A crash shows up as a freeze; the 68000 then sits in Sega's error
   handler at `$200`. Read the CPU registers from the save state (GPGX layout: D0-D7, A0-A7, PC, SR as little-endian
   longs after the sound context) and the exception frame on the stack to find the faulting instruction.
3. For new sprites, crop close-ups of each enemy by matching the entity's animation table pointer (`$0E` in the
   entity) and look at them.
4. To ship: regenerate `patch/PokeAxe-<ver>.bps` with `tools/bps.py`, verify it round-trips, and update the patched
   ROM checksums in `README.md`.

## Engine facts that matter

- **Entities**: 128-byte slots at `$FFD000` (players 0-1, map entities from `$FFD100`). x at `$1C`, base y at `$20`,
  screen y at `$18`, health `$64`, animation table `$0E`. Code holds entity pointers **sign-extended**
  (`$FFFFD100`), so range checks must use `$FFFFD100..$FFFFF000`.
- **DMA characters** (heroes, soldiers, Amazon, skeleton) stream one picture per frame. Budget per picture: heroes
  48 tiles, enemies 32 tiles. Animation tables have a flipped half; flipping is detected per frame from the original
  metasprite's H-flip bit.
- **Preloaded characters** (giants, Death Adder, knights, mounts) keep all frames in VRAM from one Nemesis block
  listed in `MapEntityGroupTileAddressTable` (`$13A74`). VRAM `$190-$4BF` is shared, so each type has a fixed tile
  budget. Death Adder's patterns start 531 tiles in (after the giants' block); his animation 11 is Death Bringer's
  throne pose with separate graphics and must be skipped. Dragon tiles 198-272 are the flames and are kept.
- **Palettes**: line 0 = heroes + HUD + skeletons (+ a second raw copy at `$2EF76` reloaded after magic). Line 1 =
  soldiers and big foes, with ~15 per-stage variants in `MapEntityGroupPaletteTable` (`$389E8`); slots 12-15 are
  overwritten by the "GO" arrow palette (`$2E6D2`), so they are fixed. Line 2 = mounts (`$38ACC`), slots 11-15 are
  the fire colours. On the select screen, lines 0-2 are **one palette at three brightness levels**.
- **Damage**: enemies lose health via `sub.b d3,$64(a0)` at 11 sites (optional `patches.two_hit_kills` in
  `mod.json`, off since 1.1). Sega's code branches into the middle of nearby
  instruction sequences (e.g. `$F39A` → `$F3A8`), so a patch may only replace that exact 4-byte instruction
  (done with `bsr.w` to a trampoline in `$FF` padding at `$140D0`). Hit depth tolerance is `moveq #8,d2` at `$BF48`.
- **Sound**: SMPS Z80 driver at ROM `$1D2F0`. Samples are 4-bit DPCM played from Z80 RAM `$0F08`; the 68000 copies a
  2512-byte block there via `$358C`/`$3594` with the pitch in `d7` (`$1F` ≈ 6030 Hz). The general sound-effect
  routine `$3652` is hooked; enemy hit sounds are `$91-$94`. Hooks must save every register the loader clobbers
  (`d0-d1/d7/a1/a5-a6`).
- **Level select**: write the level (0-7) to `$FFFE2C` on the select screen. Health/lives bytes: `$FFFE7C/$FFFE7D`.
- **Select-screen hero order**: Bulbasaur is the default; Charmander = LEFT LEFT; Squirtle = RIGHT RIGHT.
- The ROM checksum (header `$18E`) must be correct or the game will not boot; `build.py` fixes it.
- 68000 code is written in assembly and assembled at build time with vasm (`assemble`/`place` in `build.py`).
- OpenEmu resumes from an automatic save state, which restores old palettes and RAM: when testing a new build there,
  start a new game rather than continuing.
