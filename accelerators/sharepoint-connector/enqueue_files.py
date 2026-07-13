#!/usr/bin/env python3
"""
Manually enqueue specific SharePoint files for (re)indexing — no dispatcher.

The normal pipeline is:  timer -> sp_indexer_timer (dispatcher) -> sp-indexer-q
-> sp_worker.  This script lets an operator skip the dispatcher and push a
hand-picked set of files straight onto the same queue.  The existing
`sp_worker` functions pick them up and process them exactly as if the
dispatcher had enqueued them (download -> extract -> embed -> index).

Because it re-uses the connector's own `state_store.enqueue`, the message body
and queue encoding are byte-for-byte identical to a dispatcher-produced message
— there is no risk of a format mismatch.

--------------------------------------------------------------------------
INPUT
--------------------------------------------------------------------------
Provide one or more file references, each of which may be either:

  * A drive-relative path, e.g.   Reports/My Document.pdf
                                  /Reports/My Document.pdf
  * A full SharePoint URL,  e.g.  https://contoso.sharepoint.com/sites/
                                  YourSite/Shared%20Documents/Reports/My%20Document.pdf
    (this is the `source_url` / `Url` column emitted in index-files-report.csv
     and unindexed-approved-files.csv)

Pass them positionally and/or via a text file (one reference per line; blank
lines and lines starting with '#' are ignored):

  python enqueue_files.py "Reports/My Document.pdf" "Manuals/Other.pdf"
  python enqueue_files.py --paths-file ./missing.txt
  python enqueue_files.py --paths-file ./unindexed-approved-files.csv --csv-column Url

--------------------------------------------------------------------------
AUTH / PREREQUISITES
--------------------------------------------------------------------------
The script authenticates exactly like the connector (config.load_config +
SharePointClient + StateStore), so it needs:

  * Graph read access to the SharePoint site (Sites.Read.All / Files.Read.All).
  * Data-plane send access to the Storage queue
    (Storage Queue Data Message Sender on the connector's storage account).

Easiest ways to get both:
  A) Run it from a context that carries the Function App's managed identity
     (already granted both), or
  B) Set CLIENT_SECRET (+ CLIENT_ID/TENANT_ID) for an app registration that
     has the Graph app-permissions, and `az login` as a user/SP that holds the
     queue role, or
  C) `az login --scope https://graph.microsoft.com/Sites.Read.All` with an
     account that also has the queue data role (DefaultAzureCredential picks up
     the az CLI session).

Required env vars are the same ones the Function App uses. Run from the
`sharepoint-connector` directory (or set the same app settings in a .env file);
at minimum: TENANT_ID, SHAREPOINT_SITE_URL, SHAREPOINT_LIBRARIES, the storage
account settings used by state_store, SEARCH_ENDPOINT, SEARCH_INDEX_NAME, and an
embedding endpoint (only needed by the worker, not by this enqueue step).

--------------------------------------------------------------------------
NOTES
--------------------------------------------------------------------------
* `--dry-run` resolves + prints the messages but does NOT enqueue.
* A single run_id is shared by all files so run-progress tracking works and the
  batch is visible as one logical run.
* Files that cannot be resolved (wrong path, no access) are reported and
  skipped; the rest are still enqueued.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from urllib.parse import quote, unquote, urlparse

# Ensure the connector modules are importable regardless of CWD.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from config import load_config  # noqa: E402
from sharepoint_client import GRAPH_BASE, SharePointClient  # noqa: E402
from state_store import get_store  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("enqueue_files")


def _read_paths_file(path: str, csv_column: str | None) -> list[str]:
    """Read references from a text or CSV file.

    Plain text: one reference per line ('#' comments and blank lines ignored).
    CSV: pass --csv-column to pick the column holding the path/URL.
    """
    refs: list[str] = []
    if csv_column:
        import csv

        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or csv_column not in reader.fieldnames:
                raise SystemExit(
                    f"Column '{csv_column}' not found in {path}. "
                    f"Available columns: {reader.fieldnames}"
                )
            for row in reader:
                val = (row.get(csv_column) or "").strip()
                if val:
                    refs.append(val)
    else:
        with open(path, encoding="utf-8-sig") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                refs.append(line)
    return refs


def _resolve_relative_path(ref: str, drives: list[dict]) -> tuple[dict, str]:
    """Map an input reference to (drive, drive-relative path).

    A full SharePoint URL is matched against each target drive's webUrl prefix;
    everything else is treated as a path relative to the single target drive.
    """
    if ref.lower().startswith("http://") or ref.lower().startswith("https://"):
        # Normalise: decode %20 etc. and compare case-insensitively.
        ref_path = unquote(urlparse(ref).path).rstrip("/")
        best: tuple[dict, str] | None = None
        best_len = -1
        for d in drives:
            d_web = d.get("webUrl", "")
            d_path = unquote(urlparse(d_web).path).rstrip("/")
            if not d_path:
                continue
            if ref_path.lower() == d_path.lower():
                # URL points at the drive root itself — no file.
                continue
            if ref_path.lower().startswith(d_path.lower() + "/") and len(d_path) > best_len:
                best = (d, ref_path[len(d_path):].lstrip("/"))
                best_len = len(d_path)
        if best is None:
            raise ValueError(
                f"URL does not fall under any target library: {ref}"
            )
        return best
    # Relative path: requires a single unambiguous target drive.
    rel = ref.lstrip("/")
    if len(drives) != 1:
        raise ValueError(
            f"Relative path '{ref}' is ambiguous — {len(drives)} target "
            f"libraries configured. Provide a full URL instead."
        )
    return drives[0], rel


def _get_drive_item_by_path(client: SharePointClient, drive_id: str, rel_path: str) -> dict:
    """GET /drives/{id}/root:/{path} — returns the DriveItem metadata."""
    # Encode each path segment but keep the '/' separators.
    encoded = "/".join(quote(seg) for seg in rel_path.split("/"))
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{encoded}"
    return client._get(url)  # noqa: SLF001 — deliberate reuse of connector's retrying GET


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Enqueue specific SharePoint files for the sp_worker to process (no dispatcher).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="File references (drive-relative paths or full SharePoint URLs).",
    )
    parser.add_argument(
        "--paths-file",
        help="Path to a text file (one reference per line) or a CSV (use --csv-column).",
    )
    parser.add_argument(
        "--csv-column",
        help="If --paths-file is a CSV, the column holding the path/URL (e.g. Url).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and print the messages without enqueuing.",
    )
    args = parser.parse_args(argv)

    refs: list[str] = list(args.paths)
    if args.paths_file:
        refs.extend(_read_paths_file(args.paths_file, args.csv_column))

    # De-duplicate, preserving order.
    seen: set[str] = set()
    refs = [r for r in refs if not (r in seen or seen.add(r))]

    if not refs:
        parser.error("No file references provided. Pass paths and/or --paths-file.")

    logger.info(f"{len(refs)} file reference(s) to resolve")

    cfg = load_config()
    sp = SharePointClient(cfg.entra, cfg.sharepoint)
    store = get_store()

    try:
        drives = sp.get_target_drives()
        if not drives:
            logger.error("No target drives resolved — check SHAREPOINT_LIBRARIES.")
            return 2
        logger.info(f"Target libraries: {[d.get('name') for d in drives]}")

        run_id = str(uuid.uuid4())
        payloads: list[dict] = []
        failures: list[tuple[str, str]] = []

        for ref in refs:
            try:
                drive, rel = _resolve_relative_path(ref, drives)
                item = _get_drive_item_by_path(sp, drive["id"], rel)
                if "id" not in item:
                    raise ValueError("Graph response has no item id")
                if item.get("folder"):
                    raise ValueError("Reference points at a folder, not a file")
                payloads.append(
                    {
                        "run_id": run_id,
                        "drive_id": drive["id"],
                        "drive_name": drive.get("name", ""),
                        "item_id": item["id"],
                        "name": item.get("name", ""),
                        "size": item.get("size", 0),
                        "web_url": item.get("webUrl", ""),
                        "last_modified": item.get("lastModifiedDateTime", ""),
                    }
                )
                logger.info(
                    f"Resolved: {item.get('name')} "
                    f"({item.get('size', 0)} bytes) item_id={item['id']}"
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Could not resolve '{ref}': {e}")
                failures.append((ref, str(e)))

        if not payloads:
            logger.error("Nothing resolved successfully — nothing to enqueue.")
            return 2

        if args.dry_run:
            logger.info(f"[dry-run] Would enqueue {len(payloads)} message(s) with run_id={run_id}")
            for p in payloads:
                logger.info(f"[dry-run]   {p['name']} -> {p['item_id']}")
        else:
            try:
                store.record_run_start(run_id, expected=len(payloads))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Could not record run start (continuing): {e}")

            enqueued = 0
            for p in payloads:
                try:
                    store.enqueue(p)
                    enqueued += 1
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Failed to enqueue {p['name']}: {e}")
                    failures.append((p["name"], str(e)))
            logger.info(
                f"Enqueued {enqueued}/{len(payloads)} message(s) to the indexer queue "
                f"(run_id={run_id}). The sp_worker functions will process them."
            )

        if failures:
            logger.warning(f"{len(failures)} reference(s) failed:")
            for ref, err in failures:
                logger.warning(f"  - {ref}: {err}")
            return 1
        return 0
    finally:
        sp.close()


if __name__ == "__main__":
    raise SystemExit(main())
