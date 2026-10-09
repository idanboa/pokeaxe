#!/bin/sh
# usage: tools/fetch_pmd.sh <dex number, e.g. 0004>   -> assets/pmd/<dex>/
set -e
dex=$1; dir="$(dirname "$0")/../assets/pmd/$dex"; base=https://raw.githubusercontent.com/PMDCollab/SpriteCollab/master/sprite/$dex
mkdir -p "$dir"; cd "$dir"
curl -sSfO "$base/AnimData.xml"; curl -sSfO "$base/credits.txt" || true
for a in $(python3 -E -c "
import xml.etree.ElementTree as E
for a in E.parse('AnimData.xml').getroot().iter('Anim'):
    if not a.findtext('CopyOf'): print(a.findtext('Name'))"); do
  curl -sSf -o "$a-Anim.png" "$base/$a-Anim.png"; curl -sSf -o "$a-Shadow.png" "$base/$a-Shadow.png"
done
ls | wc -l
