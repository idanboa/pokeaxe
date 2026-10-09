"""Re-export reskinned characters from a built ROM with the 32X project's DataVis tool.
usage: python3 -E tools/verify.py tools/mod.json out/pokeaxe.md <outdir>"""
import json, os, struct, subprocess, sys
cfg = json.load(open(sys.argv[1])); rom = open(sys.argv[2], 'rb').read(); out = sys.argv[3]
here = os.path.dirname(os.path.abspath(__file__)); root = os.path.dirname(here)
lines = ['animations:']
for c in cfg['characters']:
    base = struct.unpack_from('>I', rom, c['tile_base_refs'][0])[0]
    pal = cfg['palette_groups'][c['palette_group']]['palettes'][0]
    lines += [f'  {c["name"]}:', '    type: DMA', f'    animation-table-address: {c["animation_table"]:#x}',
              '    animation-index: 0', f'    animation-count: {c["animation_count"] * 2}',
              f'    dma-frame-table-address: {c["dma_table"]:#x}', '    tile-data-addresses:', f'      - {base:#x}',
              f'    bounds-table-address: {c.get("bounds_table", 0x399AA if c["max_tiles"] == 48 else 0x40262):#x}',
              f'    palette-address: {pal:#x}']
os.makedirs(out, exist_ok=True)
open(f'{out}/verify.yaml', 'w').write('\n'.join(lines) + '\n')
java = f'{root}/.tools/jdk-21.0.12.1+1/Contents/Home/bin/java'
subprocess.run([java, '-jar', f'{root}/ref/ga32x/tools/DataVis/target/DataVis.jar', '-c', f'{out}/verify.yaml', '-o', out, sys.argv[2]], check=True)
