"""Content-addressed store for fetched pages.

Nothing is ever re-fetched in order to re-process. The raw bytes are written
once with their SHA-256; reprocessing reads from disk. That is what makes the
corpus frozen and the pipeline replayable.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from ..models import sha256

# Query parameters that carry no content and would otherwise break the
# "canonical URL" rule in Section 6.
_TRACKING_PREFIXES = ("utm_", "mc_", "_hs", "fbclid", "gclid", "msclkid", "ref")


def canonical_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if not any(k.lower().startswith(p) for p in _TRACKING_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path,
         urllib.parse.urlencode(query), "")
    )


class RawStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.root / "manifest.jsonl"

    def _blob_path(self, digest: str) -> Path:
        return self.root / "blobs" / digest[:2] / f"{digest}.bin"

    def has(self, digest: str) -> bool:
        return self._blob_path(digest).exists()

    def put(self, url: str, content: bytes, meta: dict) -> str:
        digest = sha256(content)
        p = self._blob_path(digest)
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            p.write_bytes(content)
        record = {
            "url": canonical_url(url),
            "sha256": digest,
            "bytes": len(content),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            **meta,
        }
        with open(self.manifest_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return digest

    def get(self, digest: str) -> bytes:
        return self._blob_path(digest).read_bytes()

    def manifest(self) -> list[dict]:
        if not self.manifest_path.exists():
            return []
        with open(self.manifest_path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
