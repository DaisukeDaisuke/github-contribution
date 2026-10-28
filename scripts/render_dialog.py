#!/usr/bin/env python3
"""Build a standalone dialog page with both themes' WebP images embedded."""
import argparse
import base64
import html
import json
from pathlib import Path


def render_dialog(directory):
    directory=Path(directory).resolve()
    report=json.loads((directory/'data.json').read_text(encoding='utf-8'))
    template=Path(__file__).resolve().parents[1]/'templates/dialog.html'
    content=template.read_text(encoding='utf-8')
    values={'__PROFILE_USER__':html.escape(report['metadata']['user'],quote=True)}
    for token,name in {
        '__DARK_PREVIEW__':'profile-dark3.webp','__LIGHT_PREVIEW__':'profile-light3.webp',
        '__DARK_FULL__':'profile-dark.webp','__LIGHT_FULL__':'profile-light.webp',
    }.items():
        values[token]='data:image/webp;base64,'+base64.b64encode((directory/name).read_bytes()).decode('ascii')
    for token,value in values.items():
        content=content.replace(token,value)
    target=directory/'dialog.html'
    target.write_text(content,encoding='utf-8')
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('dist'))
    args=parser.parse_args()
    render_dialog(args.directory)
