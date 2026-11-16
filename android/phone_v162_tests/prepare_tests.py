"""Reconstruct the exact offline reference sources from existing repo artifacts.

No downloads, credentials, trading settings, or live API calls. Refuse to replace
different local files. Run from a disposable checkout: sibling directories
core121/ and regression_hosts/ are used by the inherited regression runners.
"""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

REPO = Path(__file__).resolve().parents[2]
ANDROID = REPO/'android'
WORK = REPO.parent


def write_verified(path, raw, expected):
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Reference hash mismatch: '+str(path))
    if path.exists() and path.read_bytes() != raw:
        raise ValueError('Refusing to replace different local file: '+str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def main():
    audit = json.loads((ANDROID/'phone_1_4_2_entry_audit.json').read_text())
    raw = base64.b64decode(audit['archive_base64'], validate=True)
    expected = '5e646649c5319ff10f24ad678f6412bc7ae30d47aaf16a05518c2f8510476cda'
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('Original entry-audit archive changed')
    pins = json.loads((ANDROID/'phone_v162/phone_sources.json').read_text())['files']
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:*') as archive, \
            zipfile.ZipFile(REPO/'release-input/OKX_PROGRAM_UPDATE.zip') as fallback:
        names = set(archive.getnames())
        fixture = archive.extractfile('release_1110_repo/android/entry142_audit/fixtures.json').read()
        write_verified(Path(__file__).parent/'fixtures.json', fixture,
                       '7c7f6cf2fd542f29d74b0ba4ab3f0601e1266534f77e7b52484f02ef94086918')
        for name, digest in pins.items():
            rel = PurePosixPath(name)
            if rel.is_absolute() or '..' in rel.parts:
                raise ValueError('Invalid pinned path')
            member = 'core121/'+name
            if member in names:
                entry = archive.getmember(member)
                if not entry.isfile():
                    raise ValueError('Reference must be a regular file')
                content = archive.extractfile(entry).read()
            else:
                content = fallback.read(name)
            write_verified(WORK/'core121'/name, content, digest)
    for version in ('1_3_6', '1_4_0', '1_4_1', '1_4_2'):
        installer = ast.parse((ANDROID/f'phone_{version}_setup.py').read_text())
        payload = next(ast.literal_eval(n.value) for n in installer.body
                       if isinstance(n, ast.Assign) and n.targets[0].id == 'PAYLOAD')
        host = WORK/'regression_hosts'/('phone_v'+version.replace('_', ''))
        for name, content in payload.items():
            if Path(name).name != name:
                raise ValueError('Invalid host filename')
            raw = content.encode()
            write_verified(host/name, raw, hashlib.sha256(raw).hexdigest())
    print(f'PASS: {len(pins)} pinned core files and four prior hosts prepared offline')


if __name__ == '__main__':
    main()
