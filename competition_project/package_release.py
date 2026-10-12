"""Create a clean handoff archive; keep tests and input archive outside it."""
from pathlib import Path
import ast
import hashlib
import json
from zipfile import ZipFile, ZIP_DEFLATED
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/"K230_competition"
PREFIX="K230_competition_20261012"
files=[p for p in SOURCE.rglob("*") if p.is_file() and
       "__pycache__" not in p.parts and p.suffix not in (".pyc",".o",".exe") and
       p.name not in ("good.png","SHA256SUMS.json")]
for p in files:
    if p.suffix==".py":compile(p.read_text(encoding="utf-8-sig"),str(p),"exec")
tree=ast.parse((SOURCE/"install.py").read_text(encoding="utf-8"))
embedded=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
              and any(isinstance(t,ast.Name) and t.id=="FILES" for t in n.targets))
for name,text in embedded.items():assert text==(SOURCE/name).read_text(encoding="utf-8-sig"),name
hashes={p.relative_to(SOURCE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
manifest=SOURCE/"SHA256SUMS.json"
manifest.write_text(json.dumps(hashes,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
files.append(manifest)
output=ROOT.parent/(PREFIX+".zip")
with ZipFile(output,"w",ZIP_DEFLATED) as archive:
    for p in sorted(files):archive.write(p,PREFIX+"/"+p.relative_to(SOURCE).as_posix())
with ZipFile(output) as archive:
    assert archive.testzip() is None
    for relative,digest in hashes.items():
        assert hashlib.sha256(archive.read(PREFIX+"/"+relative)).hexdigest()==digest
print(json.dumps({"zip":str(output),"files":len(files),"bytes":output.stat().st_size,
                  "sha256":hashlib.sha256(output.read_bytes()).hexdigest()},ensure_ascii=False))
