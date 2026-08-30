#!/usr/bin/env python3
"""
Generate a Cydia/Sileo-compatible repo from the .deb files in debs/.

Creates (at the repo root): Packages, Packages.gz, Packages.bz2, and Release.

Pure Python: parses each .deb's ar archive to read its control file, so no
dpkg/apt tooling is required. Run it after adding/removing any .deb:
    python3 build_repo.py
"""

import bz2
import gzip
import hashlib
import io
import lzma
import sys
import tarfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEBS_DIR = ROOT / "debs"

RELEASE_ORIGIN = "SuperYosh23"
RELEASE_LABEL = "SuperYosh23 Repo"
RELEASE_DESCRIPTION = "SuperYosh23's iOS packages"


def decompress(data: bytes) -> bytes:
    """Try to decompress control.tar bytes (gz/bz2/xz/raw-lzma)."""
    decompressors = [
        lambda: gzip.decompress(data),
        lambda: bz2.decompress(data),
        lambda: lzma.decompress(data),  # xz
        lambda: lzma.decompress(data, format=lzma.FORMAT_ALONE),  # raw lzma
    ]
    for attempt in decompressors:
        try:
            return attempt()
        except Exception:
            continue
    raise RuntimeError("could not decompress control tar")


def read_control(deb: Path) -> str:
    """Extract the control file from a .deb (ar) archive."""
    with deb.open("rb") as f:
        if f.read(8) != b"!<arch>\n":
            raise RuntimeError(f"not an ar archive: {deb.name}")
        while True:
            header = f.read(60)
            if len(header) < 60:
                break
            name = header[:16].decode("ascii", "replace").rstrip()
            try:
                size = int(header[48:58].decode("ascii", "replace").strip() or "0")
            except ValueError:
                break
            data = f.read(size)
            if size % 2 == 1:
                f.read(1)  # ar member padding
            if name.startswith("control.tar"):
                with tarfile.open(fileobj=io.BytesIO(decompress(data)), mode="r:") as tf:
                    for member in tf.getmembers():
                        if member.name.endswith("control"):
                            content = tf.extractfile(member).read()
                            return content.decode("utf-8", "replace")
    raise RuntimeError(f"no control found in {deb.name}")


def fields_from_control(control: str) -> dict:
    """Parse a debian control block into a dict of field -> value."""
    result = {}
    current = None
    for raw_line in control.splitlines():
        if not raw_line.strip():
            continue
        if raw_line[0].isspace():
            if current is not None:
                result[current] = result[current] + "\n" + raw_line.lstrip()
            continue
        if ":" not in raw_line:
            continue
        key, _, value = raw_line.partition(":")
        current = key.strip()
        result[current] = value.strip()
    return result


def line_wrap(value: str, width: int = 79) -> str:
    """Wrap a long field value into continuation lines (init two-space indent)."""
    if len(value.encode("utf-8")) <= width:
        return value
    out = []
    line = ""
    for word in value.split(" "):
        if len((line + " " + word).strip()) > width:
            out.append(line.rstrip())
            line = "  " + word
        else:
            line = (line + " " + word).strip()
    out.append(line.rstrip())
    return "\n".join(out)


def sha(data: bytes, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    h.update(data)
    return h.hexdigest()


def build_packages() -> bytes:
    stanzas = []
    for deb in sorted(DEBS_DIR.glob("*.deb")) + sorted(ROOT.glob("*.deb")):
        control = read_control(deb)
        fieldmap = fields_from_control(control)
        required = {"Package", "Version", "Architecture"}
        missing = required - set(fieldmap)
        if missing:
            print(f"  SKIP {deb.name}: missing control fields {sorted(missing)}")
            continue

        raw = deb.read_bytes()
        fieldmap["Filename"] = str(deb.relative_to(ROOT))
        fieldmap["Size"] = str(len(raw))
        fieldmap["MD5sum"] = sha(raw, "md5")
        fieldmap["SHA1"] = sha(raw, "sha1")
        fieldmap["SHA256"] = sha(raw, "sha256")

        order = [
            "Package", "Name", "Version", "Architecture",
            "Pre-Depends", "Depends", "Conflicts", "Replaces", "Provides",
            "Installed-Size", "Maintainer", "Author", "Section", "Homepage",
            "Tag", "Description", "Icon", "Filename", "Size", "MD5sum",
            "SHA1", "SHA256",
        ]
        names = [n for n in order if n in fieldmap]
        names += [n for n in fieldmap if n not in names]

        lines = []
        for name in names:
            value = fieldmap[name]
            if name == "Description" and "\n" in value:
                desc, _, rest = value.partition("\n")
                lines.append(f"Description: {desc}")
                for sub in rest.split("\n"):
                    lines.append(" " + sub.strip())
            else:
                lines.append(f"{name}: {line_wrap(value)}")
        stanzas.append("\n".join(lines))

    stanzas.sort(key=lambda s: (fields_from_control(s).get("Package", ""),
                                fields_from_control(s).get("Version", "")))
    return ("\n\n".join(stanzas) + "\n").encode("utf-8")


def build_release(packages_data: bytes, packages_gz: bytes, packages_bz2: bytes) -> bytes:
    now = datetime.now(timezone.utc)
    file_specs = [
        ("Packages", packages_data),
        ("Packages.gz", packages_gz),
        ("Packages.bz2", packages_bz2),
    ]
    checksum_lines = {algo: [] for algo in ("MD5Sum", "SHA1", "SHA256")}
    for name, data in file_specs:
        checksum_lines["MD5Sum"].append(f" {sha(data, 'md5'):32} {len(data):8} {name}")
        checksum_lines["SHA1"].append(f" {sha(data, 'sha1'):40} {len(data):8} {name}")
        checksum_lines["SHA256"].append(f" {sha(data, 'sha256'):64} {len(data):8} {name}")

    lines = [
        f"Origin: {RELEASE_ORIGIN}",
        f"Label: {RELEASE_LABEL}",
        f"Description: {RELEASE_DESCRIPTION}",
        "Suite: stable",
        "Version: 1.0",
        "Codename: ios",
        "Architectures: iphoneos-arm arm64",
        "Components: main",
        "Date: " + now.strftime("%a, %d %b %Y %H:%M:%S UTC"),
        "Valid-Until: " + (now + timedelta(days=14)).strftime("%a, %d %b %Y %H:%M:%S UTC"),
        "",
        "MD5Sum:",
    ]
    lines += checksum_lines["MD5Sum"]
    lines += ["", "SHA1:"]
    lines += checksum_lines["SHA1"]
    lines += ["", "SHA256:"]
    lines += checksum_lines["SHA256"]
    return ("\n".join(lines) + "\n").encode("utf-8")


def main() -> int:
    debs = sorted(DEBS_DIR.glob("*.deb")) + sorted(ROOT.glob("*.deb"))
    if not debs:
        print("No .deb files found.")
        return 1

    print(f"Building repo from {len(debs)} package(s):")
    for deb in debs:
        control = fields_from_control(read_control(deb))
        print(f"  {control.get('Package', '?')}"
              f" {control.get('Version', '?')}"
              f" ({control.get('Architecture', '?')}) <- {deb.relative_to(ROOT)}")

    packages = build_packages()
    packages_gz = gzip.compress(packages, mtime=0)
    packages_bz2 = bz2.compress(packages)
    release = build_release(packages, packages_gz, packages_bz2)

    (ROOT / "Packages").write_bytes(packages)
    (ROOT / "Packages.gz").write_bytes(packages_gz)
    (ROOT / "Packages.bz2").write_bytes(packages_bz2)
    (ROOT / "Release").write_bytes(release)

    print("\nWrote:")
    for name in ("Packages", "Packages.gz", "Packages.bz2", "Release"):
        path = ROOT / name
        print(f"  {name} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())