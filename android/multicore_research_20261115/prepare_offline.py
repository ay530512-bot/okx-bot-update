"""Prepare a standalone research checkout only; never installs or starts a bot."""
from pathlib import Path
import hashlib
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORK = REPO.parent


def unpack(archive, destination, expected=None):
    if expected and hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise ValueError('archive hash mismatch')
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            target = destination / item.filename
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError('unsafe archive path')
            if item.is_dir():
                continue
            content = z.read(item)
            if target.is_symlink():
                raise ValueError('symlink destination')
            if target.exists():
                if target.read_bytes() != content:
                    raise ValueError('different existing file: '+str(target))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)


if __name__ == '__main__':
    unpack(REPO/'release-input/OKX_PROGRAM_UPDATE.zip', WORK/'core121',
           '6b2a0a90f02cca914ffc5cc0996555e8c1435b7a61618575ee94ee2ebdc2dad1')
    unpack(HERE/'host23_offline_fixture.zip', WORK/'fixture121/host-v23',
           '0645b350eab6e2b97b0591b99714859c3288abcf260f4c3a5b6776b051fc4a68')
    print('Offline files ready; no services started, no account settings read.')
