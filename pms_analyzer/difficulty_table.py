from __future__ import annotations

import csv
import json
import io
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urljoin
from urllib3.util import Retry

import sqlite3

from .analysis import DensityResult, compute_density
from .pms_parser import PMSParser


@dataclass
class DifficultyEntry:
    difficulty: str
    title: str
    subtitle: str | None
    chart_path: Path | None
    artist: str | None = None
    md5: str | None = None
    sha256: str | None = None
    total_value: float | None = None
    note_count: int | None = None


@dataclass
class DifficultyTable:
    name: str
    entries: List[DifficultyEntry]
    symbol: str | None = None


@dataclass
class ChartAnalysis:
    difficulty: str
    density: DensityResult
    entry: DifficultyEntry
    resolved_path: Path | None
    note_count: int
    total_value: float | None
    title: str
    subtitle: str | None
    md5: str | None
    sha256: str | None


SUPPORTED_SUFFIXES = {".csv", ".json"}


def load_difficulty_table(path: Path | str, *, base_dir: Optional[Path] = None) -> DifficultyTable:
    table_path = Path(path)
    if table_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported difficulty table format: {table_path.suffix}")

    entries = (
        _read_csv(table_path, base_dir=base_dir)
        if table_path.suffix.lower() == ".csv"
        else _read_json(table_path, base_dir=base_dir)
    )
    return DifficultyTable(name=table_path.stem, entries=entries)


def load_difficulty_table_from_content(
    name: str, content: str, suffix: str, *, base_dir: Optional[Path] = None, source_url: Optional[str] = None
) -> DifficultyTable:
    suffix = suffix.lower()
    if suffix in (".csv", ".json"):
        reader = _read_csv_stream if suffix == ".csv" else _read_json_stream
        entries = reader(io.StringIO(content), base_dir=base_dir or Path(tempfile.gettempdir()))
        return DifficultyTable(name=name, entries=entries)
    if suffix in (".html", ".htm"):
        return _load_bms_table_from_html(
            name, content, base_dir=base_dir or Path(tempfile.gettempdir()), source_url=source_url
        )
    raise ValueError(f"Unsupported difficulty table format: {suffix}")


def analyze_table(
    table: DifficultyTable,
    parser: PMSParser,
    *,
    terminal_window: float = 5.0,
    songdata_db: Optional[Path] = None,
    beatoraja_base: Optional[Path] = None,
) -> List[ChartAnalysis]:
    analyses: List[ChartAnalysis] = []
    for entry in table.entries:
        resolved_path = _resolve_entry_path(entry, songdata_db=songdata_db, beatoraja_base=beatoraja_base)

        if resolved_path is None:
            density = DensityResult(
                [],
                [],
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                None,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            )
            analyses.append(
                ChartAnalysis(
                    difficulty=entry.difficulty,
                    density=density,
                    entry=entry,
                    resolved_path=None,
                    note_count=entry.note_count or 0,
                    total_value=entry.total_value,
                    title=entry.title,
                    subtitle=entry.subtitle,
                    md5=entry.md5,
                    sha256=entry.sha256,
                )
            )
            continue

        parse_result = parser.parse(resolved_path)
        density = compute_density(
            parse_result.notes,
            parse_result.total_time,
            terminal_window=terminal_window,
            total_value=parse_result.total_value,
        )
        entry.note_count = entry.note_count or len(parse_result.notes)
        entry.total_value = entry.total_value or parse_result.total_value
        analyses.append(
            ChartAnalysis(
                difficulty=entry.difficulty,
                density=density,
                entry=entry,
                resolved_path=resolved_path,
                note_count=len(parse_result.notes),
                total_value=parse_result.total_value or entry.total_value,
                title=parse_result.title,
                subtitle=parse_result.subtitle,
                md5=entry.md5,
                sha256=entry.sha256,
            )
        )

    return analyses


def _read_csv(path: Path, *, base_dir: Optional[Path]) -> List[DifficultyEntry]:
    entries: List[DifficultyEntry] = []
    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            entries.append(_entry_from_row(row, base_dir or path.parent))
    return entries


def _read_json(path: Path, *, base_dir: Optional[Path]) -> List[DifficultyEntry]:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries: List[DifficultyEntry] = []
    if isinstance(data, dict):
        items = data.get("charts") or data.get("entries") or []
    else:
        items = data

    for item in items:
        row = {k: (v if v is not None else "") for k, v in item.items()}
        entries.append(_entry_from_row(row, base_dir or path.parent))
    return entries


def _read_csv_stream(stream: io.StringIO, *, base_dir: Optional[Path]) -> List[DifficultyEntry]:
    entries: List[DifficultyEntry] = []
    stream.seek(0)
    reader = csv.DictReader(stream)
    base = base_dir or Path(tempfile.gettempdir())
    for row in reader:
        entries.append(_entry_from_row(row, base))
    return entries


def _read_json_stream(stream: io.StringIO, *, base_dir: Optional[Path]) -> List[DifficultyEntry]:
    stream.seek(0)
    data = json.loads(stream.read())
    entries: List[DifficultyEntry] = []
    base = base_dir or Path(tempfile.gettempdir())

    if isinstance(data, dict):
        items = data.get("charts") or data.get("entries") or []
    else:
        items = data

    for item in items:
        row = {k: (v if v is not None else "") for k, v in item.items()}
        entries.append(_entry_from_row(row, base))
    return entries


def _entry_from_row(row: Dict[str, object], base_dir: Path) -> DifficultyEntry:
    def _get(key: str, fallback: str = "") -> str:
        value = row.get(key) if isinstance(row, dict) else None
        return str(value).strip() if value is not None else fallback

    difficulty = _get("difficulty") or _get("level") or "Unknown"
    title = _get("title") or _get("name") or Path(_get("pms_path")).stem
    subtitle = _get("subtitle") or None
    artist = _get("artist") or None
    md5 = _get("md5") or None
    sha256 = _get("sha256") or _get("hash_sha256") or None
    total_raw = _get("total") or _get("total_value")
    total_value = None
    try:
        total_value = float(total_raw) if total_raw else None
    except ValueError:
        total_value = None
    note_raw = _get("notes") or _get("note_count")
    note_count = None
    try:
        note_count = int(note_raw) if note_raw else None
    except ValueError:
        note_count = None
    pms_raw = _get("pms_path") or _get("chart")
    resolved = _resolve_path(pms_raw, base_dir) if pms_raw else None

    return DifficultyEntry(
        difficulty=difficulty,
        title=title,
        subtitle=subtitle,
        chart_path=resolved,
        artist=artist,
        md5=md5,
        sha256=sha256,
        total_value=total_value,
        note_count=note_count,
    )


def _load_bms_table_from_html(name: str, html: str, *, base_dir: Path, source_url: Optional[str]) -> DifficultyTable:
    # BMSTable形式: <meta name="bmstable" content="./header.json">
    import re

    meta_match = re.search(r'<meta[^>]+name=["\\\']bmstable["\\\'][^>]+content=["\\\']([^"\\\']+)["\\\']', html, re.IGNORECASE)
    if not meta_match:
        raise ValueError("bmstable meta tag not found in HTML")
    header_path = meta_match.group(1).strip()
    base_href = source_url if source_url else f"file://{base_dir.as_posix()}/"
    header_url = urljoin(base_href, header_path)

    try:
        header_text = _fetch_url(header_url)
        header = json.loads(header_text)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to load bmstable header: {exc}") from exc

    songlist_path = header.get("songlist") or header.get("songs") or header.get("data_url")
    if not songlist_path:
        raise ValueError("bmstable header missing songlist")
    songlist_url = urljoin(header_url, songlist_path)
    try:
        song_text = _fetch_url(songlist_url)
        songs = json.loads(song_text)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to load bmstable songlist: {exc}") from exc

    entries: List[DifficultyEntry] = []
    symbol = header.get("symbol")
    for song in songs:
        diff = str(song.get("level") or song.get("difficulty") or song.get("lr2level") or "Unknown")
        title = song.get("title") or "Unknown"
        subtitle = song.get("subtitle")
        artist = song.get("artist")
        md5 = song.get("md5") or song.get("md5_hash")
        sha256 = song.get("sha256") or song.get("sha256_hash") or song.get("sha256sum")
        notes = song.get("notes") or song.get("note")
        note_count = None
        try:
            note_count = int(notes) if notes is not None else None
        except (TypeError, ValueError):
            note_count = None
        entries.append(
            DifficultyEntry(
                difficulty=diff,
                title=str(title),
                subtitle=subtitle if subtitle else None,
                chart_path=None,
                artist=artist,
                md5=str(md5) if md5 else None,
                sha256=str(sha256) if sha256 else None,
                total_value=None,
                note_count=note_count,
            )
        )

    return DifficultyTable(name=header.get("name") or name, entries=entries, symbol=symbol)


def _fetch_url(url: str) -> str:
    import requests

    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    resp = session.get(url, timeout=30, headers={"User-Agent": "PMSChartAnalyzer/1.0"})
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def _resolve_path(value: str, base_dir: Path) -> Optional[Path]:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate if candidate.exists() else None


def _resolve_entry_path(entry: DifficultyEntry, *, songdata_db: Optional[Path], beatoraja_base: Optional[Path]) -> Optional[Path]:
    if entry.chart_path and entry.chart_path.exists():
        return entry.chart_path

    if songdata_db:
        found = find_song_in_db(songdata_db, md5=entry.md5, sha256=entry.sha256)
        if found and found.get("path"):
            raw_path = Path(str(found["path"]))
            if not raw_path.is_absolute() and beatoraja_base:
                raw_path = beatoraja_base / raw_path
            entry.chart_path = raw_path if raw_path.exists() else None
            entry.title = str(found.get("title") or entry.title)
            entry.subtitle = str(found.get("subtitle") or entry.subtitle or "")
            entry.artist = str(found.get("artist") or entry.artist or "")
            entry.note_count = entry.note_count or (int(found.get("notes")) if found.get("notes") else None)
            try:
                entry.total_value = entry.total_value or (float(found.get("total")) if found.get("total") else None)
            except (TypeError, ValueError):
                pass
            entry.md5 = entry.md5 or (found.get("md5") and str(found.get("md5")))
            entry.sha256 = entry.sha256 or (found.get("sha256") and str(found.get("sha256")))
            if entry.chart_path:
                return entry.chart_path
    return None


def find_song_in_db(db_path: Path, *, md5: str | None = None, sha256: str | None = None) -> Optional[Dict[str, object]]:
    if not db_path.exists():
        return None
    try:
        con = sqlite3.connect(str(db_path))
    except Exception:
        return None

    with con:
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        hash_keys = {
            "sha256": ["sha256", "sha256sum", "sha256_hash", "hash_sha256"],
            "md5": ["md5", "md5sum", "hash_md5"],
        }

        for table in tables:
            columns = {info[1].lower(): info[1] for info in con.execute(f"PRAGMA table_info('{table}')")}
            hash_candidates: list[tuple[str, str]] = []
            if sha256:
                for key in hash_keys["sha256"]:
                    if key in columns:
                        hash_candidates.append((columns[key], sha256))
                        break
            if md5:
                for key in hash_keys["md5"]:
                    if key in columns:
                        hash_candidates.append((columns[key], md5))
                        break

            for col, value in hash_candidates:
                try:
                    cursor = con.execute(f"SELECT * FROM '{table}' WHERE {col} = ?", (value,))
                    row = cursor.fetchone()
                except Exception:
                    continue
                if row is None:
                    continue
                desc = [d[0].lower() for d in cursor.description]
                data = dict(zip(desc, row))
                return {
                    "path": _pick_first(data, ["path", "filepath", "file", "chartpath"]),
                    "title": _pick_first(data, ["title", "name"]),
                    "subtitle": data.get("subtitle"),
                    "artist": data.get("artist"),
                    "md5": data.get("md5") or data.get("md5sum") or data.get("hash_md5"),
                    "sha256": data.get("sha256") or data.get("sha256sum") or data.get("sha256_hash") or data.get("hash_sha256"),
                    "notes": _pick_first(data, ["notes", "notecount"]),
                    "total": _pick_first(data, ["total", "totalvalue"]),
                }
    return None


def _pick_first(data: Dict[str, object], keys: list[str]) -> Optional[object]:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


__all__ = [
    "DifficultyEntry",
    "DifficultyTable",
    "ChartAnalysis",
    "load_difficulty_table",
    "analyze_table",
    "find_song_in_db",
]
