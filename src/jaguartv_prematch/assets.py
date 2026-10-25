from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


CATALOG_RELATIVE_PATH = Path("assets/poster/catalog.json")
ALLOWED_FAN_LICENSES = {"CC-BY-2.0", "CC-BY-4.0", "CC0-1.0", "operator-authorized"}


class AssetCatalogError(RuntimeError):
    """Raised when a local poster asset is not eligible for production."""


@dataclass(frozen=True)
class PosterAsset:
    asset_id: str
    kind: str
    local_path: Path
    source_url: str
    license_id: str
    license_url: str
    attribution: str
    sha256: str

    def manifest(self, repository: Path) -> dict[str, str]:
        try:
            local_path = str(self.local_path.relative_to(repository))
        except ValueError:
            local_path = str(self.local_path)
        return {
            "asset_id": self.asset_id,
            "kind": self.kind,
            "local_path": local_path,
            "source_url": self.source_url,
            "license_id": self.license_id,
            "license_url": self.license_url,
            "attribution": self.attribution,
            "sha256": self.sha256,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def approved_fan_backgrounds(repository: Path) -> list[PosterAsset]:
    """Load only local, hash-verified fan assets that may be used in a poster."""
    catalog_path = repository / CATALOG_RELATIVE_PATH
    if not catalog_path.is_file():
        raise AssetCatalogError(f"Fan-crowd asset catalog is missing: {catalog_path}")
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise AssetCatalogError(f"Fan-crowd asset catalog is unreadable: {catalog_path}") from error
    entries = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise AssetCatalogError("Fan-crowd asset catalog must contain an assets list.")

    assets: list[PosterAsset] = []
    assets_root = (repository / "assets").resolve()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("status") != "approved" or entry.get("kind") != "fan_crowd_background":
            continue
        license_id = str(entry.get("license_id") or "")
        if license_id not in ALLOWED_FAN_LICENSES:
            continue
        relative = Path(str(entry.get("local_path") or ""))
        if relative.is_absolute() or not relative.parts:
            raise AssetCatalogError(f"Catalog asset has an invalid local path: {entry.get('asset_id')}")
        local_path = (repository / relative).resolve()
        if assets_root not in local_path.parents:
            raise AssetCatalogError(f"Catalog asset escapes assets/: {entry.get('asset_id')}")
        expected_hash = str(entry.get("sha256") or "")
        if not local_path.is_file():
            raise AssetCatalogError(f"Approved fan asset is missing: {relative}")
        if len(expected_hash) != 64 or sha256_file(local_path) != expected_hash:
            raise AssetCatalogError(f"Approved fan asset hash mismatch: {relative}")
        required = ("asset_id", "source_url", "license_url", "attribution")
        if any(not str(entry.get(key) or "").strip() for key in required):
            raise AssetCatalogError(f"Approved fan asset provenance is incomplete: {relative}")
        assets.append(PosterAsset(
            asset_id=str(entry["asset_id"]),
            kind="fan_crowd_background",
            local_path=local_path,
            source_url=str(entry["source_url"]),
            license_id=license_id,
            license_url=str(entry["license_url"]),
            attribution=str(entry["attribution"]),
            sha256=expected_hash,
        ))
    if not assets:
        raise AssetCatalogError("No approved, hash-verified fan-crowd background is available.")
    return sorted(assets, key=lambda item: item.asset_id)


def choose_fan_background(repository: Path, fixture_id: str) -> PosterAsset:
    assets = approved_fan_backgrounds(repository)
    position = int(hashlib.sha256(fixture_id.encode("utf-8")).hexdigest(), 16) % len(assets)
    return assets[position]


def verified_player_asset(asset: dict[str, Any], team: str) -> PosterAsset | None:
    """Validate a supplied player photo before a face-off collage can use it."""
    if str(asset.get("club") or "").casefold().strip() != team.casefold().strip():
        return None
    if not bool(asset.get("current_club_verified")):
        return None
    if not str(asset.get("license_record") or "").strip():
        return None
    path_value = str(asset.get("local_path") or "").strip()
    expected_hash = str(asset.get("asset_hash") or "").strip()
    player_name = str(asset.get("player_name") or "").strip()
    source_url = str(asset.get("source_url") or "").strip()
    season = str(asset.get("season") or "").strip()
    retrieval_date = str(asset.get("retrieval_date") or "").strip()
    if not path_value or len(expected_hash) != 64 or not player_name or not source_url or not season or not retrieval_date:
        return None
    local_path = Path(path_value).expanduser()
    if not local_path.is_absolute():
        local_path = local_path.resolve()
    if not local_path.is_file() or sha256_file(local_path) != expected_hash:
        return None
    return PosterAsset(
        asset_id=player_name,
        kind="verified_player_portrait",
        local_path=local_path,
        source_url=source_url,
        license_id="operator-authorized",
        license_url=str(asset.get("license_record")),
        attribution=player_name,
        sha256=expected_hash,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _search_exa(query: str) -> dict[str, Any]:
    command = ["mcporter", "call", "exa.web_search_exa", f"query={query}", "numResults=5"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"status": "failed", "error": type(error).__name__, "candidates": []}
    if result.returncode != 0:
        return {"status": "failed", "error": (result.stderr or result.stdout)[-500:], "candidates": []}
    return {"status": "ok", "raw_output": result.stdout[-12000:]}


def _search_firecrawl(query: str) -> dict[str, Any]:
    key = os.environ.get("FIRECRAWL_API_KEY")
    if not key:
        return {"status": "not_configured", "reason": "FIRECRAWL_API_KEY is not configured", "candidates": []}
    payload = {
        "query": query,
        "sources": [{"type": "web"}],
        "limit": 5,
        "ignoreInvalidURLs": True,
        "scrapeOptions": {"formats": [{"type": "markdown"}]},
    }
    try:
        response = requests.post(
            "https://api.firecrawl.dev/v2/search",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=90,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, ValueError) as error:
        return {"status": "failed", "error": str(error)[:500], "candidates": []}
    web = body.get("data", {}).get("web", []) if isinstance(body, dict) else []
    candidates = []
    for item in web if isinstance(web, list) else []:
        if not isinstance(item, dict):
            continue
        markdown = str(item.get("markdown") or "")
        candidates.append({
            "title": str(item.get("title") or ""),
            "source_url": str(item.get("url") or ""),
            "source_excerpt": markdown[:1200],
        })
    return {"status": "ok", "candidates": candidates, "credits_used": body.get("creditsUsed")}


def _selected_teams(run_dir: Path) -> list[str]:
    selection = run_dir / "phase1" / "selected-fixtures.json"
    if not selection.is_file():
        return []
    try:
        fixtures = json.loads(selection.read_text(encoding="utf-8")).get("fixtures", [])
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    teams = []
    for fixture in fixtures if isinstance(fixtures, list) else []:
        if isinstance(fixture, dict):
            teams.extend(str(fixture.get(key) or "").strip() for key in ("home_team", "away_team"))
    return sorted({team for team in teams if team})


def discover_assets(run_dir: Path, *, target_date: str, dry_run: bool = False) -> dict[str, Any]:
    """Discover candidates only; downloading and approval remain an operator action."""
    teams = _selected_teams(run_dir)
    queries = [
        'site:commons.wikimedia.org/wiki/File football supporters stadium "Creative Commons Attribution"',
        *[f'site:commons.wikimedia.org/wiki/File "{team}" football supporters "Creative Commons Attribution"' for team in teams],
    ]
    queries = queries[:5]
    searches = []
    for query in queries:
        if dry_run:
            exa = {"status": "not_called_dry_run", "candidates": []}
            firecrawl = {"status": "not_called_dry_run", "candidates": []}
        else:
            exa = _search_exa(query)
            firecrawl = _search_firecrawl(query)
        searches.append({"query": query, "agent_reach_exa": exa, "firecrawl": firecrawl})
    manifest = {
        "schema_version": "jaguartv-poster-asset-discovery-v1",
        "retrieved_at": _now(),
        "target_date": target_date,
        "selected_teams": teams,
        "status": "CANDIDATES_REQUIRE_MANUAL_LICENSE_REVIEW",
        "policy": {
            "downloads_automatic": False,
            "production_eligible": False,
            "required_before_production": [
                "verify current team context for player portraits",
                "record a license or operator authorization",
                "download into approved inventory and record SHA-256",
            ],
        },
        "searches": searches,
    }
    output = run_dir / "asset-research" / f"asset-candidates-{target_date.replace('-', '')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "status": manifest["status"], "output": str(output), "query_count": len(queries)}
