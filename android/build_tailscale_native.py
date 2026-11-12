#!/usr/bin/env python3
"""Build unmodified, checksum-pinned upstream Tailscale for Android/arm64.

This is a project-built binary, not an official Tailscale release artifact.
No root, seccomp changes, binary patching, credentials or account access.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import urllib.request

GO_VERSION = '1.27.3'
GO_SHA = '65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40'
TS_VERSION = '1.104.6'
MODULE_SUM = 'h1:VjIuSsyFQ2Bp+HOtgbZCCJ7ZFTL+fULop5gmUF2bBIA='
MOD_SUM = 'h1:RROMXOJKiSHdVBeNtruULbCtqamzizsDgqQRYlCHclM='
SOURCE_COMMIT = 'c54807352ae196919497b3f8fddc3cedf88368b9'
PREFIX = 'tailscale_1.104.6_android_arm64_r2'
TAG = 'phone-tailscale-1.104.6-android-arm64-r2'
BUILD_TAGS = 'ts_omit_clientupdate,ts_omit_systray,ts_omit_ssh,ts_omit_taildrop'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(work):
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    archive = work/'go1.27.3.linux-amd64.tar.gz'
    if not archive.exists():
        print('Downloading pinned official Go toolchain', flush=True)
        with urllib.request.urlopen('https://go.dev/dl/'+archive.name, timeout=60) as r, archive.open('wb') as w:
            while chunk := r.read(1024*1024):
                w.write(chunk)
    assert digest(archive) == GO_SHA, 'Go checksum mismatch'
    if not (work/'go/bin/go').exists():
        with tarfile.open(archive) as t:
            t.extractall(work, filter='data')
    go = str(work/'go/bin/go')
    env = dict(os.environ, GOTOOLCHAIN='local', GOWORK='off', GOFLAGS='',
               GOPROXY='https://proxy.golang.org', GOSUMDB='sum.golang.org',
               GOPRIVATE='', GONOSUMDB='', GONOPROXY='')
    assert subprocess.check_output([go, 'version'], env=env, text=True).startswith('go version go'+GO_VERSION+' ')
    module = json.loads(subprocess.check_output([go, 'mod', 'download', '-json', 'tailscale.com@v'+TS_VERSION], env=env, text=True))
    assert module['Sum'] == MODULE_SUM and module['GoModSum'] == MOD_SUM
    assert module['Origin']['Hash'] == SOURCE_COMMIT
    source = Path(module['Dir'])
    env.update(GOOS='android', GOARCH='arm64', CGO_ENABLED='0')
    output = work/'out'; output.mkdir(exist_ok=True)
    bins = work/'bin'; bins.mkdir(exist_ok=True)
    ldflags = ('-s -w -X tailscale.com/version.longStamp=1.104.6-phone-android-r2 '
               '-X tailscale.com/version.shortStamp=1.104.6 '
               '-X tailscale.com/version.gitCommitStamp='+SOURCE_COMMIT)
    files = {}
    # Taildrop's Android GUI file provider is absent in standalone Termux.
    # Confirm the crashing package is absent, not merely disabled in prefs.
    deps = subprocess.check_output([go, 'list', '-mod=readonly', '-tags='+BUILD_TAGS,
            '-deps', './cmd/tailscaled'], cwd=source, env=env, text=True).splitlines()
    assert 'tailscale.com/feature/taildrop' not in deps, 'Taildrop unexpectedly linked'
    for required in ('tailscale.com/feature/androidbin', 'tailscale.com/feature/androiddns',
                     'tailscale.com/feature/acme', 'tailscale.com/wgengine/netstack'):
        assert required in deps, 'Required remote feature missing: '+required
    selected = json.loads(subprocess.check_output([go, 'list', '-mod=readonly', '-tags='+BUILD_TAGS,
            '-json', 'tailscale.com/ipn/ipnlocal'], cwd=source, env=env, text=True))
    assert 'serve.go' in selected['GoFiles'] and 'serve_disabled.go' not in selected['GoFiles']
    (output/'feature-check.json').write_text(json.dumps(dict(taildrop_linked=False,
        serve_enabled=True, android_dns_and_netmon=True, certificate_automation=True,
        netstack=True, build_tags=BUILD_TAGS.split(',')), indent=2)+'\n')
    for name in ('tailscale', 'tailscaled'):
        path = bins/name
        print('Building native Android', name, flush=True)
        subprocess.run([go, 'build', '-mod=readonly', '-trimpath', '-buildvcs=false', '-buildmode=pie',
                        '-tags='+BUILD_TAGS, '-ldflags='+ldflags,
                        '-o', str(path), './cmd/'+name], cwd=source, env=env, check=True)
        info = subprocess.check_output([go, 'version', '-m', str(path)], env=env, text=True)
        for setting in ('GOOS=android', 'GOARCH=arm64', 'CGO_ENABLED=0', '-buildmode=pie', *BUILD_TAGS.split(',')):
            assert setting in info, setting
        raw = path.read_bytes()
        assert raw[:6] == b'\x7fELF\x02\x01'
        assert struct.unpack_from('<HH', raw, 16) == (3, 183), 'Not Android arm64 PIE'
        (output/(name+'-buildinfo.txt')).write_text(info)
        files[name] = digest(path)
    packed = io.BytesIO()
    with gzip.GzipFile(fileobj=packed, mode='wb', filename='', mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.USTAR_FORMAT) as t:
            for name, path in [('tailscale', bins/'tailscale'), ('tailscaled', bins/'tailscaled'),
                               ('LICENSE', source/'LICENSE')]:
                raw = path.read_bytes()
                item = tarfile.TarInfo(PREFIX+'/'+name); item.size = len(raw)
                item.mode = 0o700 if name != 'LICENSE' else 0o644
                t.addfile(item, io.BytesIO(raw))
    package = output/(PREFIX+'.tar.gz'); package.write_bytes(packed.getvalue())
    manifest = dict(schema=1, product='okx-phone-tailscale-native', upstream_version=TS_VERSION,
                    source_commit=SOURCE_COMMIT, module_sum=MODULE_SUM, go_version=GO_VERSION,
                    goos='android', goarch='arm64', cgo_enabled=False, self_update=False,
                    taildrop=False, build_tags=BUILD_TAGS.split(','),
                    archive=package.name, sha256=digest(package), files=files,
                    device_validation='pending; cross-compilation is not an Android runtime test')
    (output/'native_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest, indent=2), flush=True)
    return output


if __name__ == '__main__':
    build(Path(sys.argv[1] if len(sys.argv)>1 else '/tmp/okx-android-native'))
