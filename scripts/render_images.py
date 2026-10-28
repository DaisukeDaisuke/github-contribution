#!/usr/bin/env python3
"""Rasterize the light and dark SVGs as matching 2x PNG images."""
import argparse
from pathlib import Path
import shutil
import subprocess


def render_pngs(directory, width=1600):
    directory = Path(directory).resolve()
    inkscape = shutil.which('inkscape')
    if not inkscape:
        raise RuntimeError('Inkscape is required to render SVG to PNG')
    results = []
    for stem in ['profile-dark','profile-light','profile-dark3','profile-light3']:
        source = directory/f'{stem}.svg'
        target = directory/f'{stem}.png'
        if not source.is_file():
            raise ValueError(f'Missing SVG: {source.name}')
        subprocess.run([
            inkscape,str(source),'--export-type=png',
            f'--export-filename={target}',f'--export-width={800 if stem.endswith("3") else width}',
        ],check=True)
        if not target.is_file() or target.stat().st_size==0:
            raise RuntimeError(f'PNG generation failed: {target.name}')
        results.append(target)
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('dist'))
    parser.add_argument('--width',type=int,default=1600)
    args=parser.parse_args()
    if args.width<1:
        parser.error('--width must be positive')
    render_pngs(args.directory,args.width)
