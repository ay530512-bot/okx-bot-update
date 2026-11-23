"""Verify and restore the immutable public research snapshot."""
import hashlib,io,json,sys,zipfile
from pathlib import Path
def restore(source,dest):
    for group in ('market','execution','evidence'):
        index=json.loads((source/f'{group}.json').read_bytes());parts=[]
        for part in index['parts']:
            data=(source/part['file']).read_bytes()
            if hashlib.sha256(data).hexdigest()!=part['sha256']:raise ValueError(('part digest',part['file']))
            parts.append(data)
        blob=b''.join(parts)
        if hashlib.sha256(blob).hexdigest()!=index['sha256']:raise ValueError(('archive digest',group))
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for f in z.infolist():
                if not (dest/f.filename).resolve().is_relative_to(dest.resolve()):raise ValueError(f.filename)
                z.extract(f,dest)
if __name__=='__main__':restore(*map(Path,sys.argv[1:]))
