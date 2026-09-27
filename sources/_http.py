"""Shared download helper for the registry adapters."""

from __future__ import annotations

from pathlib import Path

import requests

HEADERS = {"User-Agent": "SATAT-Registry/1.0 (+https://github.com/ChiragDawra)"}


def download(url: str, dest: Path, timeout: int = 120, force: bool = False) -> dict:
    """Fetch ``url`` to ``dest``.

    Returns a status dict rather than raising, because a registry that cannot
    be reached must degrade to "unavailable" in the dashboard instead of
    taking the whole pipeline down. A half-written file is never left behind:
    the download lands on a temp path and is moved into place only once the
    transfer completed.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not force:
        return {"status": "cached", "path": str(dest), "bytes": dest.stat().st_size}

    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with requests.get(url, headers=HEADERS, timeout=timeout, stream=True) as r:
            r.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
        tmp.replace(dest)
        return {"status": "ok", "path": str(dest), "bytes": dest.stat().st_size}
    except Exception as exc:                      # network, DNS, HTTP, disk
        tmp.unlink(missing_ok=True)
        return {"status": "unavailable", "path": None, "error": f"{type(exc).__name__}: {exc}"}
