#!/usr/bin/env python3
"""Build standalone installers and a SHA256 manifest, never configure this host."""
import hashlib
from pathlib import Path
import runpy

ROOT=Path(__file__).resolve().parents[1]


def main():
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    for builder in ['build_panels.py','build_observation.py']:
        runpy.run_path(str(ROOT/'tools'/builder),run_name='__main__')
    lines=[]
    for artifact in sorted(dist.glob('*.sh')):
        lines.append(hashlib.sha256(artifact.read_bytes()).hexdigest()+'  '+artifact.name)
    (dist/'SHA256SUMS').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('Paquetes generados en '+str(dist))


if __name__=='__main__':main()
