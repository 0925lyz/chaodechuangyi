from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from .api_football import load_brasileirao_membership
from .collector import FixtureCollectionError, collect_fixtures, load_fixture_file, resolve_target_date, save_collection, tomorrow_brasilia
from .competition import membership_from_fixtures
from .config import FactoryConfig
from .image2 import generate_image2, save_image_route_manifest
from .poster import compose_poster, prepare_background, resolve_fixture_crests
from .selection import recommend_fixtures


ROOT = Path(__file__).resolve().parents[2]
MONTHS_PT = ("JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ")
MONTHS_PT_FULL = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro")
TEAM_COLORS = {
    "Grêmio": "blue, black and white tricolor",
    "Gremio": "blue, black and white tricolor",
    "Internacional": "red and white",
    "Náutico": "red, blue and white",
    "Botafogo-SP": "black and white",
    "Flamengo": "red and black",
    "Palmeiras": "green and white",
    "Santos": "black and white",
    "Vasco da Gama": "black and white with a red diagonal sash",
    "Vitória": "red and black",
    "Vitoria": "red and black",
    "Boca Juniors": "blue and yellow",
    "Vélez Sarsfield": "blue and white",
    "Mirassol": "yellow and green",
}

CREST_SAFETY = (
    "Home team name and crest strictly on the LEFT, away team name and crest strictly on the RIGHT, both correct, "
    "prominent and unobstructed. Use anonymous footballers only: silhouettes, back views or cropped figures in the "
    "correct kit colours, never a recognisable real player face, name or shirt number. "
    "All visible text must be correct Brazilian Portuguese with correct accents. "
    "No invented or garbled words, no fake scores, no fake logos and no fake crests anywhere in the artwork. "
    "No betting, odds or gambling content of any kind."
)
ANTI_FIGURE = (
    "Do NOT include any animal figure, animal head, jaguar head, feline face, lion, tiger, "
    "trophy, cup, ribbon-trophy, mascot figurine, abstract emblem, sports trophy illustration, "
    "or any figurative centrepiece at all. The centre of the artwork is reserved exclusively "
    "for the two club crests, the team names, the prediction box and supporting type. "
    "Do NOT write the words 'JaguarTV', 'JAGUARTV', 'FIGURA', 'CANAL 554', or any other channel/brand "
    "wordmark anywhere in the artwork as rendered text — the JaguarTV brand logo and every channel logo "
    "(Prime Video, SporTV, Premiere, Globo, etc.) are baked into the poster after Image2 generation. "
    "Do NOT invent text labels such as 'CANAL 554', 'JAGUARTV channel', 'JaguarTV channel', "
    "any TV-network wordmark or any channel name — those overlays are added programmatically. "
    "The only figurative animal allowed anywhere is the JaguarTV brand logo, and it is baked into "
    "the poster in the upper-right corner; the video compositor must not add another copy."
)
TEAM_ZH = {
    "Arsenal": "阿森纳",
    "Barcelona": "巴塞罗那",
    "Bayern Munich": "拜仁慕尼黑",
    "Benfica": "本菲卡",
    "Boca Juniors": "博卡青年",
    "Chelsea": "切尔西",
    "Everton": "埃弗顿",
    "Fenerbahçe": "费内巴切",
    "Fenerbahce": "费内巴切",
    "Flamengo": "弗拉门戈",
    "Internacional": "巴西国际",
    "Inter Milan": "国际米兰",
    "Liverpool": "利物浦",
    "Manchester City": "曼城",
    "Manchester United": "曼联",
    "Mirassol": "米拉索尔",
    "Napoli": "那不勒斯",
    "Newcastle United": "纽卡斯尔联",
    "Nottingham Forest": "诺丁汉森林",
    "Paris Saint-Germain": "巴黎圣日耳曼",
    "Porto": "波尔图",
    "Real Madrid": "皇家马德里",
    "River Plate": "河床",
    "Roma": "罗马",
    "Santos": "桑托斯",
    "Sporting CP": "葡萄牙体育",
    "Tottenham": "热刺",
}


def run_phase1(config: FactoryConfig, run_dir: Path, fixtures_file: Path | None = None, target_date: str | None = None) -> dict[str, Any]:
    """Collect and rank candidates. This phase never starts poster production."""
    collector = config.data["collector"]
    api_key = config.env_value(collector, "api_key_env", required=False)
    if fixtures_file:
        fixtures, raw = load_fixture_file(fixtures_file)
        source = "manual_fixture_file"
    else:
        source = "collector"
        try:
            fixtures, raw = collect_fixtures(
                collector["base_url"],
                api_key=api_key,
                date=target_date or "tomorrow",
                timeout_seconds=int(collector.get("timeout_seconds", 30)),
            )
        except FixtureCollectionError as error:
            raise RuntimeError(
                "Phase 1 blocked: fixture collector has no usable data and no --fixtures-file was provided; "
                f"{error}"
            ) from error

    phase_dir = run_dir / "phase1"
    save_collection(fixtures, raw, phase_dir / "fixtures.json")
    target_iso = resolve_target_date(target_date or "tomorrow")
    wrong_dates = sorted({fixture.schedule_date for fixture in fixtures if fixture.schedule_date != target_iso})
    if wrong_dates:
        raise RuntimeError(
            f"Phase 1 blocked: fixture data does not match requested date {target_iso}: {', '.join(wrong_dates)}"
        )
    target_year = datetime.fromisoformat(target_iso).year
    api_config = config.data.get("api_football") or {}
    membership = membership_from_fixtures(target_year, fixtures)
    if api_config:
        api_key = config.env_value(api_config, "api_key_env", required=False)
        if not api_key and api_config.get("required", False) and source != "manual_fixture_file":
            raise RuntimeError("Phase 1 blocked: API-Football credentials are required for a live daily recommendation.")
        if api_key:
            fetched = load_brasileirao_membership(
                season=target_year,
                cache_path=phase_dir / "brasileirao-membership.json",
                api_key=api_key,
                endpoint=str(api_config.get("teams_endpoint") or "https://v3.football.api-sports.io/teams"),
                timeout=int(api_config.get("timeout_seconds", 30)),
            )
            if fetched.team_names:
                membership = fetched
    _write_json(phase_dir / "brasileirao-membership.json", membership.to_dict())
    recommendations = {
        "date": target_iso,
        "timezone_label": "Horário de Brasília",
        "source": source,
        "brasileirao_membership": membership.to_dict(),
        "fixtures": recommend_fixtures(fixtures, membership),
        "next_action": "Use jaguartv-prematch select with one or more recommended fixture IDs before producing posters.",
    }
    _write_json(phase_dir / "recommended-fixtures.json", recommendations)
    return {
        "ok": True,
        "status": "MANUAL_SELECTION_REQUIRED",
        "source": source,
        "collected": len(fixtures),
        "recommended": len(recommendations["fixtures"]),
        "recommendations": str(phase_dir / "recommended-fixtures.json"),
    }


def run_manual_selection(
    run_dir: Path,
    fixture_ids: list[str],
    *,
    poster_styles: dict[str, str] | None = None,
    operator: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Persist the operator-approved slate, rejecting any non-recommended fixture."""
    recommendation_path = run_dir / "phase1" / "recommended-fixtures.json"
    if not recommendation_path.is_file():
        raise RuntimeError("Manual selection blocked: run the daily recommendation phase first.")
    recommendations = _read_json(recommendation_path)
    available = {
        str(item.get("fixture_id")): item
        for item in recommendations.get("fixtures", [])
        if str(item.get("fixture_id") or "").strip()
    }
    chosen_ids = [str(item).strip() for item in fixture_ids if str(item).strip()]
    if not chosen_ids:
        raise RuntimeError("Manual selection blocked: choose at least one recommended fixture ID.")
    if len(set(chosen_ids)) != len(chosen_ids):
        raise RuntimeError("Manual selection blocked: duplicate fixture IDs are not allowed.")
    unknown = [fixture_id for fixture_id in chosen_ids if fixture_id not in available]
    if unknown:
        raise RuntimeError(f"Manual selection blocked: fixture IDs are not in today's recommendation list: {', '.join(unknown)}")

    allowed_styles = {"auto", "fan_crowd", "star_faceoff"}
    styles = poster_styles or {}
    invalid_styles = {fixture_id: style for fixture_id, style in styles.items() if style not in allowed_styles}
    if invalid_styles:
        raise RuntimeError(f"Manual selection blocked: unsupported poster styles: {invalid_styles}")
    unknown_style_ids = sorted(set(styles) - set(chosen_ids))
    if unknown_style_ids:
        raise RuntimeError(f"Manual selection blocked: poster style supplied for an unselected fixture: {', '.join(unknown_style_ids)}")

    selected = []
    for fixture_id in chosen_ids:
        fixture = dict(available[fixture_id])
        fixture["poster_style"] = styles.get(fixture_id, "auto")
        selected.append(fixture)
    payload = {
        "schema_version": "jaguartv-prematch-selection-v1",
        "date": recommendations.get("date"),
        "timezone_label": recommendations.get("timezone_label", "Horário de Brasília"),
        "operator": operator.strip(),
        "note": note.strip(),
        "selection_source": "manual_operator_selection",
        "fixtures": selected,
    }
    phase_dir = run_dir / "phase1"
    _write_json(phase_dir / "selected-fixtures.json", payload)
    _write_json(phase_dir / "selection-summary.json", {
        "ok": True,
        "status": "SELECTION_CONFIRMED",
        "selected_count": len(selected),
        "fixture_ids": chosen_ids,
        "styles": {fixture["fixture_id"]: fixture["poster_style"] for fixture in selected},
    })
    return {"ok": True, "status": "SELECTION_CONFIRMED", "selected": len(selected), "fixture_ids": chosen_ids}


def run_phase2(run_dir: Path, *, dry_run: bool = False, research_dir: Path | None = None) -> dict[str, Any]:
    selected_path = run_dir / "phase1" / "selected-fixtures.json"
    if not selected_path.is_file():
        raise RuntimeError("Phase 2 blocked: no manual selection exists. Review recommended-fixtures.json, then run select.")
    selected = _read_json(selected_path)
    fixtures = selected.get("fixtures", [])
    phase_dir = run_dir / "phase2"
    phase_dir.mkdir(parents=True, exist_ok=True)
    if not fixtures:
        report = {"ok": True, "status": "NO_CONTENT", "research_count": 0}
        _write_json(phase_dir / "research-manifest.json", report)
        return report

    records = []
    for fixture in fixtures:
        fixture_id = str(fixture["fixture_id"])
        candidates = [
            *( [research_dir / f"{fixture_id}_research.json"] if research_dir else [] ),
            phase_dir / f"{fixture_id}_research.json",
        ]
        existing = next((path for path in candidates if path.is_file()), None)
        if existing:
            evidence = _read_json(existing)
        elif dry_run:
            evidence = _dry_research(fixture)
            _write_json(phase_dir / f"{fixture_id}_research.json", evidence)
        else:
            raise RuntimeError(
                f"Phase 2 blocked: missing current research evidence for fixture {fixture_id}; "
                "provide --research-dir or rerun with --dry-run for a local bridge test"
            )
        destination = phase_dir / f"{fixture_id}_research.json"
        if existing != destination:
            shutil.copy2(existing, destination)
        records.append({"fixture_id": fixture_id, "path": str(destination.resolve()), "dry_run": dry_run})
    manifest = {"ok": True, "status": "PHASE2_COMPLETE", "research_count": len(records), "records": records}
    _write_json(phase_dir / "research-manifest.json", manifest)
    return manifest


def run_phase3(config: FactoryConfig, run_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    selected_path = run_dir / "phase1" / "selected-fixtures.json"
    if not selected_path.is_file():
        raise RuntimeError("Phase 3 blocked: no manual selection exists. Do not generate posters from recommendations.")
    selected = _read_json(selected_path)
    fixtures = selected.get("fixtures", [])
    phase_dir = run_dir / "phase3"
    if not fixtures:
        report = {"ok": True, "status": "NO_CONTENT", "poster_count": 0}
        _write_json(phase_dir / "poster-manifest.json", report)
        return report

    tasks = [_single_prompt_task(item, run_dir, position=index, dry_run=dry_run) for index, item in enumerate(fixtures)]
    crest_paths = resolve_fixture_crests(fixtures, phase_dir / "crests", required=not dry_run)
    items = []
    for task in tasks:
        prompt_path = phase_dir / "prompts" / f"{task['id']}.txt"
        raw_path = phase_dir / "raw" / f"{task['id']}.png"
        background_path = phase_dir / "backgrounds" / f"{task['id']}.png"
        foreground_path = phase_dir / "foregrounds" / f"{task['id']}.png"
        poster_path = phase_dir / "posters" / task["filename"]
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(task["prompt"], encoding="utf-8")
        if dry_run:
            _make_dry_poster(task, raw_path)
            route = [{"provider_id": "dry-run", "model_id": "none", "status": "not_called"}]
        else:
            attempts = generate_image2(task["prompt"], raw_path, config.data["image"])
            save_image_route_manifest(phase_dir / "image-routes" / f"{task['id']}.json", attempts)
            route = [item.__dict__ for item in attempts]
        prepare_background(raw_path, background_path)
        task_fixtures = [next(item for item in fixtures if _task_id(item) == task["id"])]
        compose_meta = compose_poster(
            background_path, poster_path, foreground_path, kind=task["kind"],
            fixtures=task_fixtures,
            predictions={_task_id(item): _prediction_block(item, run_dir) for item in task_fixtures},
            logo_path=ROOT / "assets/brand/jaguartv-logo.png",
            channels_root=ROOT / "assets/channels",
            crest_paths=crest_paths,
            require_crests=not dry_run,
        )
        items.append({
            "task_id": task["id"],
            "kind": task["kind"],
            "poster_style": task["poster_style"],
            "style_evidence": task["style_evidence"],
            "prompt": str(prompt_path),
            "raw_background": str(raw_path),
            "background": str(background_path),
            "foreground": str(foreground_path),
            "poster": str(poster_path),
            "compose": compose_meta,
            "image_route": route,
        })
    manifest = {"ok": True, "status": "PHASE3_COMPLETE", "poster_count": len(items), "items": items}
    _write_json(phase_dir / "poster-manifest.json", manifest)
    return manifest


def run_phase4(config: FactoryConfig, run_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Deliver validated static PNGs. Video, audio, and upload steps do not exist in this factory."""
    posters = _read_json(run_dir / "phase3" / "poster-manifest.json").get("items", [])
    phase_dir = run_dir / "phase4"
    if not posters:
        report = {"ok": True, "status": "NO_CONTENT", "poster_count": 0}
        _write_json(phase_dir / "static-delivery-manifest.json", report)
        return report
    delivery_dir = ROOT / "deliveries" / run_dir.name
    items = []
    for sequence, item in enumerate(posters, start=1):
        source = Path(item["poster"])
        if not source.is_file():
            raise RuntimeError(f"Static delivery blocked: poster is missing for {item['task_id']}")
        with Image.open(source) as poster:
            canvas = poster.size
            poster.verify()
        compose = item.get("compose") or {}
        qa = {
            "canvas": list(canvas),
            "expected_canvas": [2048, 2560],
            "correct_canvas": canvas == (2048, 2560),
            "logo_baked_once": bool(compose.get("logo_sha256")),
            "content_in_bounds": bool(compose.get("all_content_in_bounds")),
            "crest_text_clearance": bool(compose.get("crest_text_clearance")),
        }
        if not all(qa.values()):
            raise RuntimeError(f"Static delivery blocked: poster QA failed for {item['task_id']}: {qa}")
        destination = delivery_dir / f"{sequence:02d}-{source.name}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        items.append({
            "task_id": item["task_id"],
            "poster_style": item["poster_style"],
            "poster": str(source),
            "delivered_poster": str(destination),
            "qa": qa,
        })
    manifest = {
        "ok": True,
        "status": "PHASE4_COMPLETE",
        "poster_count": len(items),
        "delivery_type": "static_png_only",
        "delivery_dir": str(delivery_dir),
        "items": items,
    }
    _write_json(phase_dir / "static-delivery-manifest.json", manifest)
    return manifest


def run_phase5(config: FactoryConfig, run_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    raise RuntimeError("Phase 5 is retired: 朝的创意 delivers static PNG posters only and never uploads video.")


def run_all(config: FactoryConfig, run_dir: Path, *, dry_run: bool = False, fixtures_file: Path | None = None, research_dir: Path | None = None, target_date: str | None = None) -> dict[str, Any]:
    raise RuntimeError("Automatic full runs are disabled. Run recommend, make a manual selection, then run produce.")


def default_run_dir(target_date: str | None = None) -> Path:
    return ROOT / "runs" / (target_date or tomorrow_brasilia()).replace("-", "")


def _prediction_block(fixture: dict[str, Any], run_dir: Path) -> dict[str, str]:
    research_path = run_dir / "phase2" / f"{_task_id(fixture)}_research.json"
    if not research_path.is_file():
        return {"score": "", "probabilities": "", "tactical": ""}
    try:
        evidence = _read_json(research_path)
    except Exception:
        return {"score": "", "probabilities": "", "tactical": ""}
    entries = evidence.get("projected_or_inferred", []) if isinstance(evidence, dict) else []
    score = ""
    probabilities = ""
    tactical = ""
    for entry in entries:
        claim = str(entry.get("claim", ""))
        text = _clean_claim(entry)
        if not score and "prediction" in claim.lower() and re.search(r"\d\s*x\s*\d", text, re.IGNORECASE):
            score = text
        if not probabilities and "win/draw/loss" in claim.lower():
            probabilities = text
        if not tactical and "tactical" in claim.lower():
            tactical = text
    return {"score": score, "probabilities": probabilities, "tactical": tactical}


POSTER_STYLES = ("fan_crowd", "star_faceoff")


def _club_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _verified_faceoff_players(fixture: dict[str, Any], run_dir: Path) -> tuple[str | None, str | None]:
    """Take one licensed, current player identity per club from the research record."""
    research_path = run_dir / "phase2" / f"{_task_id(fixture)}_research.json"
    if not research_path.is_file():
        return None, None
    try:
        assets = _read_json(research_path).get("poster_assets", [])
    except (OSError, ValueError, json.JSONDecodeError):
        return None, None
    if not isinstance(assets, list):
        return None, None

    def player_for(team: str) -> str | None:
        key = _club_key(team)
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            if _club_key(str(asset.get("club") or "")) != key:
                continue
            if not str(asset.get("license_record") or "").strip():
                continue
            name = str(asset.get("player_name") or "").strip()
            if name:
                return name
        return None

    return player_for(str(fixture["home_team"])), player_for(str(fixture["away_team"]))


def _resolve_poster_style(
    fixture: dict[str, Any], run_dir: Path, *, position: int, dry_run: bool,
) -> tuple[str, dict[str, Any]]:
    requested = str(fixture.get("poster_style") or "auto")
    if requested not in {"auto", *POSTER_STYLES}:
        raise RuntimeError(f"Unsupported poster style for {_task_id(fixture)}: {requested}")
    home_star, away_star = _verified_faceoff_players(fixture, run_dir)
    eligible_for_faceoff = bool(home_star and away_star)
    if dry_run and requested == "star_faceoff":
        home_star = home_star or "an anonymous home-team footballer"
        away_star = away_star or "an anonymous away-team footballer"
        eligible_for_faceoff = True
    if requested == "star_faceoff" and not eligible_for_faceoff:
        raise RuntimeError(
            f"Star-faceoff poster blocked for {_task_id(fixture)}: current licensed player evidence is required for both teams."
        )
    if requested == "auto":
        style = "star_faceoff" if position % 2 == 1 and eligible_for_faceoff else "fan_crowd"
    else:
        style = requested
    return style, {
        "requested_style": requested,
        "eligible_for_star_faceoff": eligible_for_faceoff,
        "home_player": home_star if style == "star_faceoff" else None,
        "away_player": away_star if style == "star_faceoff" else None,
    }


def _single_prompt_task(
    fixture: dict[str, Any], run_dir: Path, *, position: int, dry_run: bool,
) -> dict[str, Any]:
    home, away = str(fixture["home_team"]), str(fixture["away_team"])
    match_date = str(fixture["schedule_date"])
    filename = f"{_zh(home)}_vs_{_zh(away)}_{_yyMMdd(match_date)}_海报.png"
    style, style_evidence = _resolve_poster_style(fixture, run_dir, position=position, dry_run=dry_run)
    factual_zone = (
        "Keep all faces, hair and shoulders clear of the central factual area "
        "(x=300..1748, y=820..1450), which is reserved for official crests, team names and VS. "
        "Leave the top 30%, central information band, and bottom 38% visually quiet. "
        "Absolutely no readable text, digits, typography, UI panels, scoreboards, logos, crests, channel marks, "
        "sponsors, watermarks, or JaguarTV imagery."
    )
    if style == "fan_crowd":
        scene = (
            "Use a powerful fan-first scene: two dense supporter sections behind the action, with the home supporters "
            f"on the far LEFT in {home} colours ({_colors(home)}) and away supporters on the far RIGHT in {away} "
            f"colours ({_colors(away)}). Faces may be atmospheric and non-identifiable; show scarves, flags, stadium "
            "lights, smoke and real match-day emotion. No footballer portrait may dominate the composition. "
        )
    else:
        scene = (
            "Use an editorial two-star face-off: exactly one front-facing, waist-up portrait of "
            f"{style_evidence['home_player']} in the current {home} kit on the far LEFT, and exactly one front-facing, "
            f"waist-up portrait of {style_evidence['away_player']} in the current {away} kit on the far RIGHT. "
            "They look toward the camera with determined expressions; no additional player portraits. "
        )
    prompt = (
        "Create a premium cinematic 4:5 pre-match football background only. "
        f"Visual context: {home} versus {away}, {fixture['competition']}. "
        f"Poster style: {style}. {scene}{factual_zone}"
    )
    return {
        "id": _task_id(fixture),
        "kind": "single",
        "filename": filename,
        "prompt": prompt,
        "title": f"{home} vs {away}",
        "poster_style": style,
        "style_evidence": style_evidence,
    }


def _schedule_prompt_tasks(fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dated = sorted(fixtures, key=lambda item: str(item.get("kickoff_at_brt", "")))
    match_date = str(dated[0]["schedule_date"])
    tasks = []
    for offset in range(0, len(dated), 8):
        page = offset // 8 + 1
        suffix = f"-{page:02d}" if len(dated) > 8 else ""
        tasks.append({
            "id": f"schedule-{_yyMMdd(match_date)}{suffix}", "kind": "schedule",
            "filename": f"{_yyMMdd(match_date)}_赛程海报{suffix}.png",
            "prompt": (
                "Create a premium 4:5 football schedule background only, with stadium depth and quiet space for a header "
                "and up to eight factual rows. Absolutely no readable text, digits, typography, UI, panels, logos, crests, "
                "channel marks, sponsors, watermarks, or JaguarTV imagery."
            ),
            "title": "Agenda JaguarTV", "fixtures": dated[offset : offset + 8],
        })
    return tasks


def _make_dry_poster(task: dict[str, str], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1024, 1280))
    pixels = image.load()
    for y in range(image.height):
        tone = round(24 + 50 * y / image.height)
        for x in range(image.width):
            pixels[x, y] = (8, tone, 38)
    image.save(output)


def _dry_research(fixture: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "jaguartv-prematch-research-v1",
        "dry_run": True,
        "fixture_id": fixture["fixture_id"],
        "retrieval_time": _now(),
        "source_records": [{
            "source_url": fixture.get("source_url", ""),
            "platform": "fixture-file",
            "publication_time": fixture.get("retrieved_at", ""),
            "retrieval_time": _now(),
            "source_excerpt": fixture.get("source_text", ""),
            "normalized_summary": "Dry-run bridge evidence from the fixture record only.",
            "confidence": "dry-run",
        }],
    }


def _motion_prompt(item: dict[str, Any], master: Path) -> str:
    return (
        f"Animate only this text-free 9:16 football background for exactly 4 seconds: {master.name}. "
        "Use stadium lights, crowd depth, restrained sparks and cloth movement. Do not add text, scores, "
        "team graphics, channel icons, logos, watermarks, UI, or new people. The factual foreground is "
        "locked and composited locally after generation."
    )


def _loop_video(image: Path, output: Path, seconds: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1", "-i", str(image), "-t", str(seconds), "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)], check=True, timeout=120)


def _check_duration(path: Path, expected: float) -> None:
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=True, timeout=30)
    actual = float(result.stdout.strip())
    if abs(actual - expected) > 0.25:
        raise RuntimeError(f"{path.name} duration {actual:.2f}s did not match {expected:.2f}s")


WEEKDAY_PT = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo")
DOWNLOAD_SENTENCE = "Acesse jaguartvbrasil.com/baixar-app para baixar."
TIKTOK_CAPTION_LIMIT = 360
TIKTOK_TITLE_LIMIT = 100
REQUIRED_HASHTAGS = ("#jaguartv", "#iptv")


def _captions(run_dir: Path, items: list[dict[str, Any]]) -> dict[str, Any]:
    selected = _read_json(run_dir / "phase1" / "selected-fixtures.json")
    fixtures = selected.get("fixtures", [])
    date_iso = _run_date_iso(run_dir)
    return {
        "schema_version": "jaguartv-prematch-captions-v1",
        "language": "pt-BR",
        "timezone_label": "Horário de Brasília",
        "tiktok_policy": {
            "commercial_content_disclosure_required": True,
            "ai_generated_content_label_required": True,
            "max_hashtags": 5,
        },
        "items": [_caption_for(run_dir, item, fixtures, date_iso) for item in items],
        "fixture_count": len(fixtures),
    }


def _caption_for(run_dir: Path, item: dict[str, Any], fixtures: list[dict[str, Any]], date_iso: str) -> dict[str, Any]:
    weekday = WEEKDAY_PT[datetime.fromisoformat(date_iso).weekday()]
    if item.get("kind") == "schedule" or not _fixture_for(run_dir, item["task_id"]):
        hashtags = ["#futebol", "#brasileirao", "#palpites", "#jaguartv", "#iptv"]
        body = (
            f"🗓️ Agenda de {weekday}: {len(fixtures)} jogos para ficar de olho. "
            "Confira os confrontos e horários no vídeo. Jaguar TV no Android e TV Box."
        )
        return {
            "task_id": item["task_id"],
            "title": _short_text(f"Jogos de {weekday}: horários e onde assistir", TIKTOK_TITLE_LIMIT),
            "description": _tiktok_caption(body, hashtags),
            "hashtags": hashtags,
        }

    fx = _fixture_for(run_dir, item["task_id"]) or {}
    home, away = str(fx.get("home_team")), str(fx.get("away_team"))
    competition = str(fx.get("competition") or "")
    score = _predicted_score(run_dir, item["task_id"])
    tactical = _tactical_point(run_dir, item["task_id"])
    hashtags = _hashtags(home, away, competition)
    score_only = _score_only(score)
    prediction = f"{home} {score_only} {away}" if score_only else score
    tactical_copy = _short_text(tactical, 90)
    if tactical_copy and not tactical_copy.endswith((".", "!", "?", "…")):
        tactical_copy += "."
    body = (
        f"🔥 Jogaço hoje: {home} x {away}, às {fx.get('kickoff_at_brt')}, pela {competition}. "
        f"Meu palpite: {prediction}."
        f"{(' ' + tactical_copy) if tactical_copy else ''} "
        "Quer acompanhar? Jaguar TV no Android e TV Box."
    )
    return {
        "task_id": item["task_id"],
        "title": _prematch_title(home, away, score_only),
        "description": _tiktok_caption(body, hashtags),
        "hashtags": hashtags,
    }


def _hashtags(home: str, away: str, competition: str) -> list[str]:
    candidates = [
        _compact_hashtag(home),
        _compact_hashtag(away),
        _competition_hashtag(competition),
        "#futebol",
        "#palpites",
    ]
    selected: list[str] = []
    for tag in candidates:
        if tag not in selected and tag not in REQUIRED_HASHTAGS:
            selected.append(tag)
        if len(selected) == 3:
            break
    return selected + list(REQUIRED_HASHTAGS)


def _tag(value: str) -> str:
    value = value.lower()
    replacements = str.maketrans({"á": "a", "à": "a", "ã": "a", "â": "a", "é": "e", "ê": "e", "í": "i", "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ü": "u", "ç": "c"})
    return re.sub(r"[^a-z0-9]+", "", value.translate(replacements)) or "futebol"


def _compact_hashtag(value: str) -> str:
    translated = value.lower().translate(str.maketrans({"á": "a", "à": "a", "ã": "a", "â": "a", "é": "e", "ê": "e", "í": "i", "ó": "o", "ô": "o", "õ": "o", "ú": "u", "ü": "u", "ç": "c"}))
    ignored = {"associacao", "club", "clube", "da", "das", "de", "do", "dos", "ec", "esporte", "fc", "football", "futebol", "saf", "sc"}
    words = [word for word in re.findall(r"[a-z0-9]+", translated) if word not in ignored]
    joined = "".join(words)
    if joined and len(joined) <= 20:
        return f"#{joined}"
    short = next((word for word in words if len(word) <= 20), "futebol")
    return f"#{short}"


def _competition_hashtag(value: str) -> str:
    slug = _tag(value)
    aliases = (
        (("championsleague", "ligadoscampeoes"), "#championsleague"),
        (("libertadores",), "#libertadores"),
        (("sudamericana", "sulamericana"), "#sulamericana"),
        (("brasileirao", "campeonatobrasileiro"), "#brasileirao"),
        (("copadobrasil",), "#copadobrasil"),
        (("premierleague",), "#premierleague"),
    )
    for names, hashtag in aliases:
        if any(name in slug for name in names):
            return hashtag
    return _compact_hashtag(value)


def _score_only(score: str) -> str:
    found = re.search(r"\b(\d+)\s*[xX]\s*(\d+)\b", score)
    return f"{found.group(1)} x {found.group(2)}" if found else ""


_SENTENCE_BREAKS = (". ", "! ", "? ")
_CLAUSE_BREAKS = (", ", "; ", ": ")


def _drop_open_bracket(prefix: str) -> str:
    """Drop back before an unclosed "(" so a trimmed quote never leaves it hanging."""
    if prefix.count("(") > prefix.count(")"):
        return prefix[: prefix.rfind("(")].rstrip()
    return prefix


def _short_text(value: str, limit: int) -> str:
    """Shorten to ``limit`` characters, preferring to end on a readable break.

    A caption embeds the shortened text inside a longer sentence, so a cut landing
    in the middle of a clause reads as a typo ("...defendendo baixo e apostando
    nas."). Preference order: a whole sentence inside the budget, then the last clause
    break that still fills at least half (or a third) of the budget, then a plain
    word-boundary ellipsis so the reader can still see that the quote was trimmed.
    The result never exceeds ``limit``.
    """
    value = " ".join(str(value).split())
    if len(value) <= limit:
        return value
    window = value[:limit]
    boundary = max((window.rfind(mark) for mark in _SENTENCE_BREAKS), default=-1)
    if boundary >= limit // 2:
        return window[: boundary + 1]
    for floor in (limit // 2, limit // 3):
        clause = max((window.rfind(mark) for mark in _CLAUSE_BREAKS), default=-1)
        if clause >= floor:
            return f"{_drop_open_bracket(window[:clause]).rstrip('.,;:!?')}..."
    shortened = value[: limit - 3].rsplit(" ", 1)[0].rstrip(".,:;!?")
    return f"{shortened or value[:limit - 3]}..."


def _prematch_title(home: str, away: str, score: str) -> str:
    prediction = f": palpite {score}" if score else ": palpite e onde assistir"
    suffix = " e onde assistir" if score else ""
    return _short_text(f"{home} x {away}{prediction}{suffix}", TIKTOK_TITLE_LIMIT)


def _tiktok_caption(body: str, hashtags: list[str]) -> str:
    suffix = f" {DOWNLOAD_SENTENCE} {' '.join(hashtags)}"
    return f"{_short_text(body, TIKTOK_CAPTION_LIMIT - len(suffix))}{suffix}"


def _predicted_score(run_dir: Path, task_id: str) -> str:
    """Render the projected score line as "Home 1 x 1 Away".

    Only the home side and the two digits used to survive, so every published caption read
    "Palpite JaguarTV: Coritiba 1 x 1." -- a truncated scoreline that never named the away
    team. The trailing team name is captured too, with a fallback for claims that stop at the
    digits.
    """
    claim = _projected_claim(run_dir, task_id, 0)
    found = re.search(
        r"([A-Za-zÀ-ÿ][\wÀ-ÿ .'-]*?)\s+(\d)\s*[xX]\s*(\d)\s*([A-Za-zÀ-ÿ][\wÀ-ÿ .'-]*)?",
        claim,
    )
    if not found:
        return f"{claim}" if claim else "jogo aberto, decisão nos detalhes"
    line = f"{found.group(1).strip()} {found.group(2)} x {found.group(3)}"
    away = (found.group(4) or "").strip()
    return f"{line} {away}".strip()


def _tactical_point(run_dir: Path, task_id: str) -> str:
    for entry in _projected_entries(run_dir, task_id):
        if "tactical" in str(entry.get("claim", "")).lower():
            return _clean_claim(entry)
    return ""


def _projected_claim(run_dir: Path, task_id: str, index: int) -> str:
    entries = _projected_entries(run_dir, task_id)
    return _clean_claim(entries[index]) if index < len(entries) else ""


def _projected_entries(run_dir: Path, task_id: str) -> list[dict[str, Any]]:
    path = run_dir / "phase2" / f"{task_id}_research.json"
    if not path.is_file():
        return []
    try:
        evidence = _read_json(path)
    except Exception:
        return []
    entries = evidence.get("projected_or_inferred", []) if isinstance(evidence, dict) else []
    return [entry for entry in entries if isinstance(entry, dict)]


def _clean_claim(entry: dict[str, Any]) -> str:
    portuguese = str(entry.get("claim_pt", "")).strip()
    if portuguese:
        return portuguese
    claim = str(entry.get("claim", "")).strip()
    return re.sub(r"^Editorial\s+(prediction|tactical point|win/draw/loss read)\s*:\s*", "", claim, flags=re.IGNORECASE).strip()


def _upload_metadata(run_dir: Path, item: dict[str, Any]) -> dict[str, Any]:
    fx = _fixture_for(run_dir, item.get("task_id", ""))
    home = str(fx.get("home_team") or "").strip() if fx else ""
    away = str(fx.get("away_team") or "").strip() if fx else ""
    if fx:
        match_name = f"{home} vs {away}" if (home and away) else (item.get("task_id") or "unknown match")
    else:
        match_name = f"Agenda JaguarTV {_date_pt(_run_date_iso(run_dir))}"
    return {
        "category": "pre_match_prediction",
        "match_name": match_name,
        "match_date": (fx.get("schedule_date") if fx else None) or _run_date_iso(run_dir),
        "match_time_sao_paulo": _match_time_iso((fx.get("schedule_date") if fx else None) or _run_date_iso(run_dir), (fx.get("kickoff_at_brt") if fx else None) or "00:00"),
        "competition": (fx.get("competition") or "") if fx else "",
        "home_team": home,
        "away_team": away,
        "channels": (fx.get("channels") or ["Jaguar TV"]) if fx else ["Jaguar TV"],
        "kickoff_at_brt": (fx.get("kickoff_at_brt") or "") if fx else "",
        "match_info": {"content_category": "赛前预测", "task_id": item["task_id"], "timezone_label": "Horário de Brasília"},
        "metadata": {"artifact_revision": _sha256(Path(item["final"])), "run_dir": str(run_dir)},
    }


def _match_time_iso(date: str, kickoff: str) -> str:
    date = str(date or "").strip()
    time = str(kickoff or "").strip()
    if not date or not time:
        return ""
    if len(time) == 5:  # HH:MM -> HH:MM:SS
        time = f"{time}:00"
    return f"{date}T{time}-03:00"


def _run_date_iso(run_dir: Path) -> str:
    name = run_dir.name
    match = re.fullmatch(r"(\d{8})(?:_batch\d+)?", name)
    if match:
        value = match.group(1)
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    return tomorrow_brasilia()


def _fixture_for(run_dir: Path, task_id: str) -> dict[str, Any] | None:
    """Locate the selected fixture matching a build-manifest task_id."""
    candidates = (run_dir / "phase1" / "selected-fixtures.json", run_dir / "phase1" / "fixtures.json")
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = _read_json(path)
        except Exception:
            continue
        fixtures = list(data.get("fixtures", []))
        payload_fixtures = data.get("source_payload", {}).get("fixtures", []) if isinstance(data.get("source_payload"), dict) else []
        fixtures.extend(payload_fixtures)
        for fx in fixtures:
            if fx.get("fixture_id") == task_id or _task_id(fx) == task_id:
                return fx
    return None


def _colors(team: str) -> str:
    return TEAM_COLORS.get(team, TEAM_COLORS.get(_zh(team), f"the authentic {team} kit colours"))


def _zh(name: str) -> str:
    return TEAM_ZH.get(name, name)


def _yyMMdd(value: str) -> str:
    parsed = datetime.fromisoformat(value).date()
    return parsed.strftime("%y%m%d")


def _date_long_pt(value: str) -> str:
    parsed = datetime.fromisoformat(value).date()
    return f"{parsed.day:02d} de {MONTHS_PT_FULL[parsed.month - 1]} de {parsed.year}"


def _date_pt(value: str) -> str:
    parsed = datetime.fromisoformat(value).date()
    return f"{parsed.day:02d} {MONTHS_PT[parsed.month - 1]} {parsed.year}"


def _task_id(fixture: dict[str, Any]) -> str:
    raw = str(fixture.get("fixture_id") or f"{fixture.get('home_team')}-{fixture.get('away_team')}-{fixture.get('schedule_date')}")
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw).strip("-") or hashlib.sha256(raw.encode()).hexdigest()[:12]


def _run_date(run_dir: Path) -> str:
    return run_dir.name if re.fullmatch(r"\d{8}", run_dir.name) else tomorrow_brasilia().replace("-", "")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
