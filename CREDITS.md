# Credits

## Pokémon sprites — PMD SpriteCollab

Character sprites come from the [PMD SpriteCollab](https://github.com/PMDCollab/SpriteCollab) project, licensed
[CC BY-NC 4.0](https://github.com/PMDCollab/SpriteCollab/blob/master/LICENSE.md). In PokéAxe they were **modified**:
rescaled (1.25×–2×), recoloured to Mega Drive palettes, split into hardware sprites, and combined with
procedurally drawn attack effects.

| Pokémon | Sprite credits (from SpriteCollab `credits.txt`) |
|---|---|
| Bulbasaur (#0001) | CHUNSOFT |
| Charmander (#0004) | CHUNSOFT |
| Charizard (#0006) | CHUNSOFT, Emboarger |
| Squirtle (#0007) | CHUNSOFT |
| Pikachu (#0025) | CHUNSOFT |
| Machop (#0066) | CHUNSOFT, Emboarger |
| Machamp (#0068) | CHUNSOFT |
| Marowak (#0105) | CHUNSOFT |
| Rhydon (#0112) | CHUNSOFT |
| Jynx (#0124) | CHUNSOFT |
| Scizor (#0212) | CHUNSOFT |
| Tyranitar (#0248) | CHUNSOFT |

"CHUNSOFT" marks sprites originating from Pokémon Mystery Dungeon (© Nintendo / Creatures Inc. / GAME FREAK inc.,
developed by Spike Chunsoft).

## Pokémon cries

Legacy cries from [PokeAPI/cries](https://github.com/PokeAPI/cries). All audio © The Pokémon Company. Converted to
the Golden Axe sound driver's 4-bit DPCM format at about 6 kHz.

## Golden Axe research

- [jvisser/golden-axe-32x-edition](https://github.com/jvisser/golden-axe-32x-edition) — reverse-engineering notes
  and tools for the Mega Drive version (entity, animation, DMA, palette and map formats). PokéAxe would not exist
  without this work.
- Everything else (sound driver and DPCM samples, select screen, HUD, preloaded entity graphics, damage code) was
  reverse-engineered for this project with an emulator harness and disassembly.

## Tools

- [Genesis Plus GX](https://github.com/libretro/Genesis-Plus-GX) — emulator core used for testing and the trailer
- [vasm](http://sun.hasenbraten.de/vasm/) — 68000 assembler
- [Capstone](https://www.capstone-engine.org/) and [z80dis](https://pypi.org/project/z80dis/) — disassembly
- [FFmpeg](https://ffmpeg.org/) via imageio-ffmpeg — audio conversion and video encoding

## Original game

Golden Axe © SEGA 1989.
Pokémon © Nintendo / Creatures Inc. / GAME FREAK inc. / The Pokémon Company.
