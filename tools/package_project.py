"""Build a reproducible handoff ZIP from an explicit file list (no machine data)."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NAME="K230_vision_20261011"

def main():
    entries={}
    programs=("k230_gx_vision.py","k230_silver_rgb.py","k230_red_check.py",
              "k230_gx_self_test.py","k230_install_autostart.py")
    for name in programs:
        entries[name]=ROOT/"examples"/name
        entries["examples/"+name]=ROOT/"examples"/name
    for name in ("README.md","开始使用.md"):
        entries[name]=ROOT/name
    for directory,pattern in (("stm32","*.c"),("stm32","*.h"),("tools","*.py"),
                              ("tools","requirements-pc.txt"),("tests","*.py"),("tests","*.c")):
        for path in (ROOT/directory).glob(pattern):
            if path.name=="test_color_blocks.py": continue  # historical LAB implementation
            entries[path.relative_to(ROOT).as_posix()]=path
    # Desktop legacy test is excluded because the old LAB program is not in this bundle.
    for name in ("gx-k230-port.md","stm32-vision-protocol.md","2027-handling-vision-requirements.md","progress.md"):
        entries["docs/"+name]=ROOT/"docs"/name
    for directory in ("assets/qr","assets/aruco","assets/color","reference/gx-silver-original"):
        for path in (ROOT/directory).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                entries[path.relative_to(ROOT).as_posix()]=path
    manifest={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in sorted(entries.items())}
    output=ROOT/(NAME+".zip")
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,path in sorted(entries.items()):
            archive.write(path,NAME+"/"+name)
        archive.writestr(NAME+"/SHA256SUMS.json",json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip(): raise OSError("ZIP integrity failure")
        for name,digest in manifest.items():
            if hashlib.sha256(archive.read(NAME+"/"+name)).hexdigest()!=digest:
                raise OSError("ZIP content mismatch: "+name)
        assert all(NAME+"/"+name in archive.namelist() for name in programs)
    print(json.dumps({"path":str(output),"files":len(entries)+1,"bytes":output.stat().st_size,
                      "sha256":hashlib.sha256(output.read_bytes()).hexdigest()},ensure_ascii=False))

if __name__=="__main__": main()
