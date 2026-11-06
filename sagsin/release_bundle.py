"""Build a reviewable source/demo ZIP with a SHA256 manifest; no operational DB."""
import argparse
import hashlib
import json
import platform
import subprocess
import zipfile
from pathlib import Path
from .paths import ROOT


def candidates():
    roots = ['backend', 'frontend', 'sagsin', 'tests',
             'storage/input/global_ground_nodes', 'storage/input/acceptance_20261031',
             'storage/output/acceptance_20261031_final']
    allowed = {'.py', '.js', '.mjs', '.html', '.css', '.csv', '.json', '.txt', '.md', '.jpg', '.png'}
    for name in roots:
        for path in sorted((ROOT / name).rglob('*')):
            if path.is_file() and path.suffix in allowed and '__pycache__' not in path.parts:
                yield path
    for pattern in ('*.md', 'requirements*.txt', 'setup-distributed.ps1', '.gitignore'):
        yield from sorted(ROOT.glob(pattern))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():parser.error('Refusing to overwrite an existing release')
    report = ROOT / 'storage/output/acceptance_20261031_final/methodology.json'
    if not report.exists() or not json.loads(report.read_text())['complete']:
        parser.error('Complete the acceptance matrix first')
    files = sorted(set(candidates()))
    manifest = dict(version=1, python=platform.python_version(), platform=platform.platform(),
                    git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    working_tree=subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True),
                    files={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in files:archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr('release-manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(args.output) as archive:
        assert archive.testzip() is None
        for name, digest in manifest['files'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest, name
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix('.sha256').write_text(digest + '  ' + args.output.name + '\n', encoding='ascii')
    print(json.dumps(dict(zip=str(args.output), files=len(files), sha256=digest)))


if __name__ == '__main__':
    main()
