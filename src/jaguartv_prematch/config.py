from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .credentials import CredentialUnavailable, keychain_secret


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class FactoryConfig:
    path: Path
    data: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> "FactoryConfig":
        config_path = Path(path).expanduser().resolve()
        with config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        cls._validate(data)
        return cls(config_path, data)

    @staticmethod
    def _validate(data: dict[str, Any]) -> None:
        required = ("collector", "text", "image")
        missing = [key for key in required if key not in data]
        if missing:
            raise ConfigurationError(f"Missing configuration sections: {', '.join(missing)}")

        text = data["text"]
        if not all(str(text.get(key) or "").strip() for key in ("provider_id", "primary_model_id", "fallback_model_id")):
            raise ConfigurationError("Text provider and model routes must be configured")

        image = data["image"]
        if image.get("model_id") != "gpt-image-2":
            raise ConfigurationError("Poster generation model must be gpt-image-2")
        if (image.get("primary") or {}).get("provider_id") != "active-large-model-api":
            raise ConfigurationError("The active large-model API must be the primary Image2 route")
        if (image.get("fallback") or {}).get("provider_id") != "apimart":
            raise ConfigurationError("APIMart must remain the explicit secondary Image2 route")

    def env_value(self, section: dict[str, Any], field: str, *, required: bool = True) -> str:
        env_name = str(section.get(field))
        if not env_name:
            if required:
                raise ConfigurationError(f"Missing environment variable name in {field}")
            return ""
        value = os.environ.get(env_name, "").strip()
        if not value:
            # Protected credential store: macOS Keychain, service name == env var name.
            # Secrets are never persisted into config, manifests, filenames or logs.
            try:
                value = keychain_secret(env_name)
            except CredentialUnavailable:
                value = ""
        if required and not value:
            raise ConfigurationError(f"Required credential is not set: {env_name}")
        return value
