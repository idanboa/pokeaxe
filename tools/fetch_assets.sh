#!/bin/sh
# Download everything the build needs that is not in this repo:
# PMD SpriteCollab sprites (CC BY-NC 4.0) and legacy Pokémon cries (via PokeAPI/cries).
set -e
here="$(cd "$(dirname "$0")" && pwd)"
for dex in 0001 0004 0007 0025 0066 0124 0105 0068 0248 0212 0112 0006; do
  "$here/fetch_pmd.sh" "$dex" >/dev/null && echo "sprites $dex"
done
mkdir -p "$here/../assets/cries"
for n in 25 66 124 105 68 248 212 112 6; do
  curl -sSf -o "$here/../assets/cries/$n.ogg" "https://raw.githubusercontent.com/PokeAPI/cries/main/cries/pokemon/legacy/$n.ogg" && echo "cry $n"
done
