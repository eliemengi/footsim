"""Small, dependency-free locale and catalog helpers for FootSim.

The catalog files are deliberately shared by Flask/Jinja and the vanilla
frontend.  ``en`` is the safe product fallback: a missing translation must
never make a view or an API status unusable.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


SUPPORTED_LOCALES = ("de", "en")
DEFAULT_LOCALE = "en"
LANGUAGE_COOKIE = "footsim_lang"

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CATALOG_DIRECTORY = _PROJECT_ROOT / "static" / "i18n"
_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z0-9_]+)\}")


def normalize_supported_locale(value: object) -> str | None:
    """Return a supported locale for a single locale token, if any.

    ``de-DE``, ``de_AT`` and other German-family locales intentionally map to
    ``de``.  Unsupported input is kept distinct from the final English
    fallback so malformed cookies cannot override a valid browser language.
    """

    if not isinstance(value, str):
        return None

    token = value.strip().lower().replace("_", "-")
    if not token:
        return None

    base = token.split("-", 1)[0]
    if base == "de":
        return "de"
    if base == "en":
        return "en"
    return None


def locale_from_browser_header(header: str | None) -> str | None:
    """Resolve the highest-priority supported ``Accept-Language`` entry.

    Browsers commonly send an unsupported primary language followed by a
    supported preference (for example ``fr-FR, de;q=0.9``).  Treating only
    the first token would disagree with the client-side ``navigator.languages``
    selection and prematurely fall back to English.
    """

    if not header:
        return None

    candidates: list[tuple[float, int, str]] = []
    for index, raw_item in enumerate(header.split(",")):
        parts = [part.strip() for part in raw_item.split(";")]
        normalized = normalize_supported_locale(parts[0] if parts else None)
        if not normalized:
            continue

        quality = 1.0
        for parameter in parts[1:]:
            if not parameter.lower().startswith("q="):
                continue
            try:
                quality = float(parameter.split("=", 1)[1])
            except ValueError:
                quality = 0.0
            break

        if quality > 0:
            candidates.append((quality, -index, normalized))

    return max(candidates)[2] if candidates else None


def resolve_locale(
    explicit: object = None,
    persisted: object = None,
    browser_language: str | None = None,
) -> str:
    """Apply the documented selection order without raising on bad input."""

    for candidate in (explicit, persisted):
        normalized = normalize_supported_locale(candidate)
        if normalized:
            return normalized

    return locale_from_browser_header(browser_language) or DEFAULT_LOCALE


@lru_cache(maxsize=len(SUPPORTED_LOCALES))
def load_catalog(locale: str) -> dict[str, str]:
    """Load a flat UTF-8 catalog; malformed content safely becomes empty."""

    normalized = normalize_supported_locale(locale) or DEFAULT_LOCALE
    path = _CATALOG_DIRECTORY / f"{normalized}.json"
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str)}


def _interpolate(template: str, params: Mapping[str, Any]) -> str:
    """Replace known placeholders while leaving a missing one readable."""

    return _PLACEHOLDER_PATTERN.sub(
        lambda match: str(params[match.group(1)])
        if match.group(1) in params else match.group(0),
        template,
    )


def translate(key: str, locale: str = DEFAULT_LOCALE, **params: Any) -> str:
    """Translate ``key`` with English fallback and a non-crashing key fallback."""

    localized = load_catalog(locale)
    fallback = load_catalog(DEFAULT_LOCALE)
    template = localized.get(key) or fallback.get(key) or key
    return _interpolate(template, params)
