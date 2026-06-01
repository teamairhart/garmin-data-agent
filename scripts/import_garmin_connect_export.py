#!/usr/bin/env python3
"""Flatten Garmin Connect web exports into a folder of .fit files.

Garmin Connect (watch users, no head unit) gives you FIT data two ways:

  1. "Export Original" on a single activity  -> a small .zip holding one .fit
  2. Account "Export Your Data" (GDPR)        -> one large .zip with FIT files
     buried under DI_CONNECT/..., often individually zipped or gzipped.

This script accepts EITHER (a single .zip, several .zips, or an already-extracted
folder) and recursively unpacks nested .zip / .gz containers, then copies every
.fit file it finds into a single flat output folder ready for export_fit_folder.py.

It is stdlib-only and read-only on the source (it never modifies your download).

Usage:
    python scripts/import_garmin_connect_export.py <archive.zip | folder> [more...] \
        [--output-dir "/Users/jonathan_airhart/DevProjects/Fitness Data/Partner_Garmin"]

Then analyze:
    python scripts/export_fit_folder.py "<that output dir>" --output-dir exports/partner
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

DEFAULT_OUTPUT = "/Users/jonathan_airhart/DevProjects/Fitness Data/Partner_Garmin"

# A valid FIT file carries the ASCII tag ".FIT" at bytes 8-11 of its header.
FIT_MAGIC = b".FIT"


def is_fit_file(path: Path) -> bool:
    """True if the file's header has the .FIT magic (guards against junk)."""
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
        return len(header) >= 12 and header[8:12] == FIT_MAGIC
    except OSError:
        return False


def short_hash(path: Path) -> str:
    """First 8 hex chars of the file's SHA-1 — used to disambiguate name clashes
    and skip exact duplicates (the GDPR export often repeats files)."""
    h = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def iter_source_fits(source: Path, workdir: Path):
    """Yield paths to every .fit file reachable from `source`, recursively
    unpacking nested .zip and .gz containers into `workdir`."""
    if source.is_dir():
        for child in sorted(source.rglob("*")):
            if child.is_file():
                yield from _handle_file(child, workdir)
    elif source.is_file():
        yield from _handle_file(source, workdir)
    else:
        print(f"  ! skipping (not found): {source}", file=sys.stderr)


def _handle_file(path: Path, workdir: Path):
    name = path.name.lower()
    if name.endswith(".fit"):
        yield path
    elif name.endswith(".zip"):
        try:
            sub = Path(tempfile.mkdtemp(dir=workdir, prefix="zip_"))
            with zipfile.ZipFile(path) as zf:
                zf.extractall(sub)
            yield from iter_source_fits(sub, workdir)
        except (zipfile.BadZipFile, OSError) as exc:
            print(f"  ! bad zip, skipped: {path.name} ({exc})", file=sys.stderr)
    elif name.endswith(".gz"):
        # e.g. "12345_ACTIVITY.fit.gz" or "<id>.gz"
        out_name = path.name[:-3]
        if not out_name.lower().endswith(".fit"):
            out_name += ".fit"
        out_path = Path(tempfile.mkdtemp(dir=workdir, prefix="gz_")) / out_name
        try:
            with gzip.open(path, "rb") as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            yield out_path
        except OSError as exc:
            print(f"  ! bad gzip, skipped: {path.name} ({exc})", file=sys.stderr)
    # everything else (json, csv, images, etc.) is ignored


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Flatten Garmin Connect exports into a folder of .fit files."
    )
    parser.add_argument(
        "sources", nargs="+",
        help="One or more .zip archives and/or extracted folders from Garmin Connect.",
    )
    parser.add_argument(
        "-o", "--output-dir", default=DEFAULT_OUTPUT,
        help=f"Where to place the flattened .fit files (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    copied, skipped_dupe, skipped_nonfit = 0, 0, 0
    seen_hashes: set[str] = set()

    with tempfile.TemporaryDirectory(prefix="garmin_import_") as tmp:
        workdir = Path(tmp)
        for raw in args.sources:
            source = Path(raw).expanduser()
            print(f"Scanning: {source}")
            for fit in iter_source_fits(source, workdir):
                if not is_fit_file(fit):
                    skipped_nonfit += 1
                    continue
                digest = short_hash(fit)
                if digest in seen_hashes:
                    skipped_dupe += 1
                    continue
                seen_hashes.add(digest)

                target = out_dir / fit.name
                if target.exists():
                    # name clash but different content -> disambiguate with hash
                    target = out_dir / f"{fit.stem}_{digest}{fit.suffix}"
                shutil.copy2(fit, target)
                copied += 1

    print("\n--- Import complete ---")
    print(f"  .fit files copied:        {copied}")
    print(f"  duplicates skipped:       {skipped_dupe}")
    print(f"  non-FIT/invalid skipped:  {skipped_nonfit}")
    print(f"  output folder:            {out_dir}")
    if copied:
        print("\nNext step:")
        print(f'  python scripts/export_fit_folder.py "{out_dir}" --output-dir exports/partner')


if __name__ == "__main__":
    main()
