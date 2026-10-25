from __future__ import annotations

import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import FactoryConfig
from .credentials import resolve_base_url, resolve_secret
from .routing import CodexTextRouter
from .runtime import resolve_command


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def run_preflight(config: FactoryConfig, repository: Path) -> dict[str, Any]:
    checks: list[Check] = []
    for command in ("codex",):
        resolved = resolve_command(command)
        checks.append(Check(command, "ok" if resolved else "failed", resolved or "command not found"))

    text = config.data["text"]
    route = CodexTextRouter(text["provider_id"]).verify(text["primary_model_id"])
    checks.append(Check("text_route", route.status, route.sanitized_error or route.model_id))

    image = config.data["image"]
    for route_name in ("primary", "fallback"):
        route_config = image[route_name]
        try:
            model_present = _image_capability(route_config, image["model_id"])
            configured = model_present
        except Exception:
            configured = False
        checks.append(Check(f"image_{route_name}", "ok" if configured else "blocked",
                            route_config["provider_id"]))

    required_assets = [
        repository / "assets/brand/jaguartv-logo.png",
    ]
    for asset in required_assets:
        checks.append(Check(f"asset:{asset.name}", "ok" if asset.is_file() else "failed", str(asset)))
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "checks": [asdict(check) for check in checks],
        "production_ready": all(check.status in {"ok", "configured"} for check in checks),
    }
    return report
def _image_capability(route: dict[str, Any], model_id: str) -> bool:
    base_url = resolve_base_url(route)
    key = resolve_secret(route)
    endpoint = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
    request = urllib.request.Request(
        endpoint,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return model_id in {str(item.get("id")) for item in payload.get("data", []) if isinstance(item, dict)}
