"""File readers, config loading, schema drift detection, and row quarantine."""

import csv
import json
import re
from pathlib import Path
from typing import Any

import yaml


class SchemaDriftError(ValueError):
    """A source column has no configured canonical name."""


def load_config(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or not {"paths", "columns", "statuses"} <= config.keys():
        raise ValueError(f"Configuration is incomplete: {path}")
    return config


def normalize_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def read_records(path: Path, source: str) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"Expected a JSON array in {path}")
        return payload
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def canonicalize_headers(
    records: list[dict[str, Any]], source: str, config: dict[str, Any]
) -> list[dict[str, Any]]:
    aliases = config["columns"][source]
    if not records:
        return []
    observed = set(records[0])
    unknown = sorted(column for column in observed if normalize_header(column) not in aliases)
    if unknown:
        raise SchemaDriftError(
            f"{source}: unmapped column(s) {unknown}; add each source column to "
            f"config.yaml under columns.{source} with its canonical name."
        )
    translated = {
        column: aliases[normalize_header(column)] for column in observed
    }
    canonical: list[dict[str, Any]] = []
    for row in records:
        result: dict[str, Any] = {}
        for original, value in row.items():
            target = translated[original]
            if target in result and result[target] not in (None, "") and value not in (None, ""):
                raise SchemaDriftError(
                    f"{source}: multiple input columns map to {target!r}; update columns.{source}."
                )
            result[target] = value
        canonical.append(result)
    return canonical
