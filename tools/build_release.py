"""Build the Windows x64 legacy add-on ZIP (run with Python and pip >= 22.3)."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PYTHON_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
PYTHON_SHA256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"


def prepare():
    runtime = ROOT / "runtime"
    runtime.mkdir(exist_ok=True)
    archive = ROOT / "dist" / "python-embed.zip"
    urllib.request.urlretrieve(PYTHON_URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != PYTHON_SHA256:
        raise RuntimeError("Embedded Python checksum mismatch")
    with zipfile.ZipFile(archive) as package:
        package.extractall(runtime)
    (runtime / "python311._pth").write_text(
        "python311.zip\n.\nLib/site-packages\nimport site\n", encoding="utf8")
    subprocess.run([sys.executable, "-m", "pip", "--python", str(runtime / "python.exe"),
                    "install", "--only-binary=:all:", "-r", str(ROOT / "requirements-runtime.txt")], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--target", str(ROOT / "vendor"),
                    "rpyc==6.0.2", "plumbum==2.0.2"], check=True)


def build(output):
    if not (ROOT / "runtime/Lib/site-packages/amulet").is_dir():
        raise RuntimeError("Run with --prepare first to assemble the private runtime")
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for directory in ("mods", "schem", "schemcache", "saves", "resourcepacks"):
            archive.writestr(f"BaiGave_Plugin/{directory}/", "")
        for name in files:
            path = ROOT / name
            if not name or not path.is_file():
                continue
            if name.startswith(("wheels/", "mods/", "schemcache/", ".github/")):
                continue
            if name in ("site-packages.zip", "blender_manifest.toml"):
                continue
            archive.write(path, "BaiGave_Plugin/" + name)
        for directory in ("runtime", "vendor"):
            for path in (ROOT / directory).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    archive.write(path, "BaiGave_Plugin/" + path.relative_to(ROOT).as_posix())
    print(f"Built {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    (ROOT / "dist").mkdir(exist_ok=True)
    if args.prepare:
        prepare()
    build(args.output or ROOT / "dist/BaiGave_Plugin-1.1.0-blender5.2-windows-x64.zip")
