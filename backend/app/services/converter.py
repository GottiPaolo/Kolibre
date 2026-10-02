"""
Format conversion via Calibre's `ebook-convert` CLI.

Engine choice: ebook-convert is the same converter Calibre Desktop uses —
by far the most robust open-source ebook converter — at the deliberate cost
of shipping Calibre inside the Docker image (+~600MB, see backend/Dockerfile).
No Python conversion library comes close for MOBI/PDF output.

Concurrency choice: conversion runs SYNCHRONOUSLY inside the request — no
job queue, no polling endpoint. This is a personal server: conversions are
occasional, one user at a time, and uvicorn has no request timeout. The
endpoint offloads this blocking call to the threadpool (via
starlette.concurrency.run_in_threadpool in books.py), so the event loop
stays free while ebook-convert churns.
"""
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Optional

logger = logging.getLogger("kolibre.services.converter")

# Explicit override wins over any auto-discovery (useful for a non-standard
# install location, or to point tests at a fake binary).
EBOOK_CONVERT_ENV_VAR = "KOLIBRE_EBOOK_CONVERT"

# Fallback locations when the binary isn't on PATH: macOS app bundle (dev
# machine), then the two common Linux spots (distro package / official
# installer, the latter being what the Docker image would use if it ever
# switches from apt to calibre's own installer).
_KNOWN_LOCATIONS = (
    "/Applications/calibre.app/Contents/MacOS/ebook-convert",  # macOS
    "/usr/bin/ebook-convert",       # Linux, distro package (Docker image)
    "/opt/calibre/ebook-convert",   # Linux, official calibre installer
)

# Supported targets → output file extension handed to ebook-convert (which
# infers the output format from it). `html` maps to `.htmlz` on purpose:
# ebook-convert's "web page" output is HTMLZ, a zip archive containing
# index.html + images/styles — Calibre's standard single-file web format.
# Plain `.html` output would scatter loose asset files around the output
# dir; HTMLZ keeps the "send the book as a web page" use case one-file.
TARGET_EXTENSIONS = {
    "html": "htmlz",
    "mobi": "mobi",
    "pdf": "pdf",
    "txt": "txt",
}

# ebook-convert --version output, cached per resolved binary path (the
# subprocess call costs ~1-2s on macOS, way too slow to run on every
# convert-info poll from the GUI).
_version_cache: dict = {}


class ConversionError(Exception):
    """Conversion failed (bad input, engine error, timeout). Message is
    human-readable and safe to surface in an HTTP error detail."""


def find_ebook_convert() -> Optional[str]:
    """Resolves the ebook-convert binary: env override → PATH → known
    per-OS install locations. Returns None when nothing is found."""
    override = os.environ.get(EBOOK_CONVERT_ENV_VAR)
    if override:
        return override if os.path.isfile(override) and os.access(override, os.X_OK) else None

    on_path = shutil.which("ebook-convert")
    if on_path:
        return on_path

    for candidate in _KNOWN_LOCATIONS:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _get_version(binary: str) -> Optional[str]:
    if binary not in _version_cache:
        try:
            proc = subprocess.run(
                [binary, "--version"], capture_output=True, text=True, timeout=30,
            )
            _version_cache[binary] = proc.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            _version_cache[binary] = None
    return _version_cache[binary]


def converter_info() -> dict:
    """Availability info for GUI gating: {available, path, version,
    supported_targets}. Cheap to call repeatedly (version is cached)."""
    binary = find_ebook_convert()
    if not binary:
        return {
            "available": False, "path": None, "version": None,
            "supported_targets": sorted(TARGET_EXTENSIONS),
        }
    return {
        "available": True,
        "path": binary,
        "version": _get_version(binary),
        "supported_targets": sorted(TARGET_EXTENSIONS),
    }


def convert_file(source_path: str, target_fmt: str, timeout: int = 300) -> str:
    """
    Converts `source_path` to `target_fmt` (a TARGET_EXTENSIONS key,
    case-insensitive) and returns the absolute path of the converted file,
    which lives inside a dedicated fresh temp directory.

    OWNERSHIP: the caller must remove that temp directory
    (shutil.rmtree(os.path.dirname(returned_path))) once done with the file
    — via try/finally, or a starlette BackgroundTask when the file is
    streamed back as the response body. On any failure the temp dir is
    cleaned up here and ConversionError is raised with a readable message.
    """
    binary = find_ebook_convert()
    if not binary:
        raise ConversionError(
            "Conversione non disponibile: ebook-convert non trovato. "
            "Installa Calibre oppure imposta KOLIBRE_EBOOK_CONVERT."
        )

    ext = TARGET_EXTENSIONS.get((target_fmt or "").lower())
    if not ext:
        raise ConversionError(
            f"Formato di destinazione non supportato: {target_fmt!r} "
            f"(supportati: {', '.join(sorted(TARGET_EXTENSIONS))})"
        )
    if not os.path.isfile(source_path):
        raise ConversionError(f"File sorgente non trovato: {source_path}")

    # Dedicated per-conversion dir under the system temp dir: a fixed name
    # inside it is safe (no collisions between concurrent conversions), and
    # cleanup is a single rmtree.
    tmp_dir = tempfile.mkdtemp(prefix="kolibre-convert-")
    output_path = os.path.join(tmp_dir, f"output.{ext}")
    try:
        proc = subprocess.run(
            [binary, source_path, output_path],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ConversionError(
            f"Conversione interrotta: superato il limite di {timeout} secondi. "
            "Il file potrebbe essere troppo grande o complesso."
        )
    except OSError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise ConversionError(f"Impossibile eseguire ebook-convert: {exc}")

    if proc.returncode != 0 or not os.path.exists(output_path):
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # Last stderr lines carry Calibre's actual error; the full output is
        # pages of progress noise.
        stderr_tail = "\n".join((proc.stderr or "").strip().splitlines()[-5:])
        logger.error("ebook-convert failed (rc=%s): %s", proc.returncode, stderr_tail)
        raise ConversionError(
            f"Conversione fallita (ebook-convert, codice {proc.returncode})."
            + (f" Dettaglio: {stderr_tail}" if stderr_tail else "")
        )

    return output_path
