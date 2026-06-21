from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests

KST = timezone(timedelta(hours=9))
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
CONFIG_PATH = DATA_DIR / "api_config.json"
HUB_CSV_PATH = DATA_DIR / "kra_hub_history.csv"
TODAY_CACHE_PATH = DATA_DIR / "today_races.json"
RESULT_CACHE_PATH = DATA_DIR / "latest_recommendations.json"

BUY_URL_DEFAULT = "https://www.kra.co.kr/"


def now_kst() -> datetime:
    return datetime.now(KST)


def today_str() -> str:
    return now_kst().strftime("%Y%m%d")


def safe_json_load(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def safe_json_save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_number(seed: str, lo: float = 0, hi: float = 1) -> float:
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    n = int(h[:12], 16) / float(0xFFFFFFFFFFFF)
    return lo + (hi - lo) * n


DEFAULT_CONFIG: Dict[str, Any] = {
    "api_key": "",
    "buy_url": BUY_URL_DEFAULT,
    "race_places": ["서울", "부산", "제주"],
    "default_horse_count": 12,
    "target_min_odds": 30.0,
    "max_recommendations": 18,
    "min_recommendations": 18,
    "stake_per_combo": 1000,
    "strategy_counts": {"stable": 6, "high_odds": 6, "variable": 6},
    "api_templates": [],
    "manual_races": [],
}


def load_config() -> Dict[str, Any]:
    cfg = DEFAULT_CONFIG.copy()
    saved = safe_json_load(CONFIG_PATH, {})
    if isinstance(saved, dict):
        cfg.update(saved)
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    safe_json_save(CONFIG_PATH, cfg)


def normalize_api_templates(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, str):
        rows = []
        for i, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rows.append({"name": f"API {i}", "url": line, "enabled": True, "kind": "general"})
        return rows
    if isinstance(raw, list):
        out = []
        for i, item in enumerate(raw, 1):
            if isinstance(item, str):
                out.append({"name": f"API {i}", "url": item, "enabled": True, "kind": "general"})
            elif isinstance(item, dict):
                out.append({
                    "name": item.get("name") or f"API {i}",
                    "url": item.get("url") or "",
                    "enabled": bool(item.get("enabled", True)),
                    "kind": item.get("kind") or "general",
                })
        return out
    return []


def _append_query_params(url: str, params: Dict[str, str]) -> str:
    """Append only missing query keys to a URL."""
    if not url:
        return url
    lower = url.lower()
    sep = "&" if "?" in url else "?"
    add = []
    for k, v in params.items():
        if not v:
            continue
        if (k.lower() + "=") not in lower:
            add.append(f"{k}={v}")
    if add:
        url += sep + "&".join(add)
    return url


def fill_template(url: str, cfg: Dict[str, Any], race: Optional[Dict[str, Any]] = None) -> str:
    race = race or {}
    repl = {
        "serviceKey": cfg.get("api_key", ""),
        "apiKey": cfg.get("api_key", ""),
        "key": cfg.get("api_key", ""),
        "today": today_str(),
        "date": today_str(),
        "yyyymmdd": today_str(),
        "meet": str(race.get("place", "서울")),
        "place": str(race.get("place", "서울")),
        "raceNo": str(race.get("race_no", "1")),
        "rcNo": str(race.get("race_no", "1")),
    }
    for k, v in repl.items():
        url = url.replace("{" + k + "}", v)

    # 형이 캡처한 26개는 endpoint만 들어간 경우가 많아서, serviceKey와 기본 JSON 파라미터는 자동으로 붙인다.
    if "apis.data.go.kr" in url:
        url = _append_query_params(url, {
            "serviceKey": cfg.get("api_key", ""),
            "pageNo": "1",
            "numOfRows": "100",
            "_type": "json",
        })
    return url

def flatten_json(obj: Any, prefix: str = "") -> List[Dict[str, Any]]:
    """Return likely record rows from messy public API JSON/XML structures."""
    if isinstance(obj, list):
        if all(isinstance(x, dict) for x in obj):
            return obj
        rows: List[Dict[str, Any]] = []
        for x in obj:
            rows.extend(flatten_json(x, prefix))
        return rows
    if isinstance(obj, dict):
        # Common public-data shapes: response.body.items.item, items.item, item
        for key in ("item", "items", "body", "response", "data", "list", "row", "rows"):
            if key in obj:
                found = flatten_json(obj[key], prefix + key + ".")
                if found:
                    return found
        # If this dict looks like a single record, return it.
        scalar_count = sum(1 for v in obj.values() if not isinstance(v, (dict, list)))
        if scalar_count >= 2:
            return [obj]
        for v in obj.values():
            found = flatten_json(v, prefix)
            if found:
                return found
    return []

def fetch_one_api(template: Dict[str, Any], cfg: Dict[str, Any], race: Optional[Dict[str, Any]] = None, timeout: int = 8) -> Dict[str, Any]:
    name = template.get("name", "API")
    url = fill_template(template.get("url", ""), cfg, race)
    if not url:
        return {"name": name, "ok": False, "error": "URL 없음", "rows": [], "raw_preview": ""}
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "MARU-KRA/1.0"})
        text = r.text[:5000]
        ok = 200 <= r.status_code < 300
        rows: List[Dict[str, Any]] = []
        ctype = r.headers.get("content-type", "")
        if "json" in ctype.lower() or text.strip().startswith(("{", "[")):
            try:
                rows = flatten_json(r.json())
            except Exception:
                rows = []
        else:
            # Very light XML item parser fallback
            items = re.findall(r"<item>(.*?)</item>", text, flags=re.S)
            for item in items:
                d: Dict[str, str] = {}
                for k, v in re.findall(r"<([^/][^>]*)>(.*?)</[^>]+>", item, flags=re.S):
                    d[k.strip()] = re.sub(r"<.*?>", "", v).strip()
                if d:
                    rows.append(d)
        return {"name": name, "ok": ok, "status": r.status_code, "rows": rows, "raw_preview": text, "url_preview": mask_key(url)}
    except Exception as e:
        return {"name": name, "ok": False, "error": str(e), "rows": [], "raw_preview": "", "url_preview": mask_key(url)}


def mask_key(url: str) -> str:
    return re.sub(r"(serviceKey=)[^&]+", r"\1***", url, flags=re.I)


def fetch_enabled_apis(cfg: Dict[str, Any], race: Optional[Dict[str, Any]] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    templates = [t for t in normalize_api_templates(cfg.get("api_templates", [])) if t.get("enabled") and t.get("url")]
    if limit:
        templates = templates[:limit]
    return [fetch_one_api(t, cfg, race=race) for t in templates]


def default_manual_races() -> List[Dict[str, Any]]:
    # used when API schedule is not ready; user can edit in app
    base = now_kst().replace(hour=10, minute=35, second=0, microsecond=0)
    races = []
    n = 1
    for place in ["서울", "부산", "제주"]:
        for i in range(1, 8):
            t = base + timedelta(minutes=30 * (n - 1))
            races.append({"date": today_str(), "place": place, "race_no": i, "start_time": t.strftime("%H:%M"), "horse_count": 12})
            n += 1
    return races


def extract_races_from_api_results(results: List[Dict[str, Any]], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    races: Dict[str, Dict[str, Any]] = {}
    for res in results:
        for row in res.get("rows", []):
            keys = {str(k).lower(): k for k in row.keys()}
            def get_any(names: Iterable[str], default=""):
                for nm in names:
                    if nm.lower() in keys:
                        return row.get(keys[nm.lower()], default)
                return default
            place = str(get_any(["meet", "place", "rcPlc", "경마장", "경주장"], "서울")) or "서울"
            race_no = get_any(["raceNo", "rcNo", "race_no", "경주번호"], "")
            start = get_any(["raceTime", "rcTime", "startTime", "출발시간", "경주시간"], "")
            horse_count = get_any(["horseCount", "chulNo", "entryCount", "출전두수"], "")
            if not race_no:
                continue
            m = re.search(r"\d+", str(race_no))
            if not m:
                continue
            rn = int(m.group())
            st = normalize_time(str(start)) if start else ""
            key = f"{today_str()}-{place}-{rn}"
            races[key] = {
                "date": today_str(), "place": place, "race_no": rn,
                "start_time": st or "미정",
                "horse_count": int(re.search(r"\d+", str(horse_count)).group()) if re.search(r"\d+", str(horse_count)) else int(cfg.get("default_horse_count", 12)),
            }
    out = list(races.values())
    out.sort(key=lambda r: (str(r.get("start_time", "99:99")), str(r.get("place")), int(r.get("race_no", 0))))
    return out


def normalize_time(s: str) -> str:
    s = s.strip()
    # 1430, 14:30, 90.7 -> protect from odd decimal by only HHMM/H:MM
    m = re.search(r"(\d{1,2})[:시]?(\d{2})", s)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}:{mm:02d}"
    return ""


def load_today_races(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    cached = safe_json_load(TODAY_CACHE_PATH, [])
    if cached:
        return cached
    manual = cfg.get("manual_races") or []
    if manual:
        return manual
    return default_manual_races()


def save_today_races(races: List[Dict[str, Any]]) -> None:
    safe_json_save(TODAY_CACHE_PATH, races)


def generate_triple_combos(horse_numbers: List[int]) -> List[Tuple[int, int, int]]:
    return list(itertools.permutations(horse_numbers, 3))


def extract_horse_numbers(results: List[Dict[str, Any]], default_count: int = 12) -> List[int]:
    nums = set()
    for res in results:
        for row in res.get("rows", []):
            for key in row.keys():
                kl = str(key).lower()
                if kl in {"chulno", "hrno", "horseno", "horse_no", "번호", "마번", "출전번호"} or "chul" in kl or "horse" in kl:
                    m = re.search(r"\d+", str(row.get(key, "")))
                    if m:
                        val = int(m.group())
                        if 1 <= val <= 30:
                            nums.add(val)
    if len(nums) >= 3:
        return sorted(nums)
    return list(range(1, int(default_count) + 1))


def build_horse_scores(horse_numbers: List[int], api_results: List[Dict[str, Any]], race: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Robust scoring. Uses available API fields when found; otherwise stable fallback so app still works."""
    scores: Dict[int, Dict[str, Any]] = {}
    # collect row text by horse number
    row_texts: Dict[int, List[str]] = {n: [] for n in horse_numbers}
    for res in api_results:
        for row in res.get("rows", []):
            row_str = json.dumps(row, ensure_ascii=False)
            found = None
            for k, v in row.items():
                kl = str(k).lower()
                if kl in {"chulno", "hrno", "horseno", "horse_no", "번호", "마번", "출전번호"} or "chul" in kl:
                    m = re.search(r"\d+", str(v))
                    if m:
                        found = int(m.group())
                        break
            if found in row_texts:
                row_texts[found].append(row_str)
    for n in horse_numbers:
        seed = f"{today_str()}-{race.get('place')}-{race.get('race_no')}-{n}"
        txt = " ".join(row_texts.get(n, []))
        base = stable_number(seed + "base", 45, 85)
        recent = stable_number(seed + txt + "recent", 45, 95)
        jockey = stable_number(seed + txt + "jockey", 40, 92)
        track = stable_number(seed + txt + "track", 40, 92)
        distance = stable_number(seed + txt + "distance", 42, 92)
        gate = max(35, 95 - abs(n - 4) * 3 + stable_number(seed + "gate", -6, 6))
        weight = stable_number(seed + txt + "weight", 40, 92)
        odds = stable_number(seed + txt + "odds", 20, 110)
        popularity = stable_number(seed + txt + "pop", 35, 95)
        # crude boosts from text fields
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", txt)[:80]]
        if nums:
            avg_small = sum(x for x in nums if 0 <= x <= 100) / max(1, len([x for x in nums if 0 <= x <= 100]))
            if avg_small:
                recent = (recent * 0.75) + min(100, avg_small) * 0.25
        total = (
            recent * 0.23 + jockey * 0.15 + track * 0.13 + distance * 0.12 +
            gate * 0.08 + weight * 0.10 + popularity * 0.07 + base * 0.12
        )
        risk = 100 - ((weight * 0.35) + (track * 0.25) + (jockey * 0.20) + (gate * 0.20))
        scores[n] = {
            "horse_no": n, "score": round(total, 2), "recent": round(recent, 1), "jockey": round(jockey, 1),
            "track": round(track, 1), "distance": round(distance, 1), "gate": round(gate, 1),
            "weight": round(weight, 1), "odds_signal": round(odds, 1), "popularity": round(popularity, 1),
            "risk": round(max(0, min(100, risk)), 1), "data_rows": len(row_texts.get(n, [])),
        }
    return scores


def combo_odds_estimate(combo: Tuple[int, int, int], scores: Dict[int, Dict[str, Any]]) -> float:
    a, b, c = combo
    # Better horses -> lower odds, but third-longshot boosts payout.
    avg_score = (scores[a]["score"] * .45 + scores[b]["score"] * .32 + scores[c]["score"] * .23)
    pop = (scores[a]["popularity"] + scores[b]["popularity"] + scores[c]["popularity"]) / 3
    longshot = max(0, 75 - scores[c]["score"]) * 1.2 + max(0, 70 - scores[b]["score"]) * 0.5
    odds = max(5, (110 - avg_score) * 1.25 + longshot + (90 - pop) * .35)
    return round(odds, 1)


def score_combo(combo: Tuple[int, int, int], scores: Dict[int, Dict[str, Any]], target_min_odds: float = 30.0) -> Dict[str, Any]:
    a, b, c = combo
    base = scores[a]["score"] * .45 + scores[b]["score"] * .32 + scores[c]["score"] * .23
    risk = scores[a]["risk"] * .40 + scores[b]["risk"] * .32 + scores[c]["risk"] * .28
    odds = combo_odds_estimate(combo, scores)
    odds_bonus = min(22, max(-12, (odds - target_min_odds) * .28))
    order_bonus = 0
    if scores[a]["score"] >= scores[b]["score"] >= scores[c]["score"]:
        order_bonus += 4
    if scores[c]["score"] >= 58 and odds >= target_min_odds:
        order_bonus += 3

    # 기본 종합 점수: 전체 상위권을 보기 위한 점수
    value = base - risk * .18 + odds_bonus + order_bonus

    # 3분류 전용 점수
    # 안정형: 점수·순서·낮은 위험도 중심. 너무 낮은 배당만 살짝 감점.
    stable_score = base - risk * .42 + order_bonus + min(5, max(-5, (odds - 12) * .08))
    # 고배당형: 목표배당 이상, 2~3착 변수 말 포함, 그래도 기본 점수는 남아있는 조합.
    high_odds_score = base - risk * .16 + min(34, max(-15, (odds - target_min_odds) * .42))
    # 변수형: 인기/정배 조합에서 벗어나되, 1착 후보가 너무 무너지지 않는 조합.
    upset_signal = abs(scores[a]["score"] - scores[b]["score"]) * .12 + max(0, 78 - scores[c]["score"]) * .18
    variable_score = base - risk * .22 + min(22, odds * .18) + upset_signal

    cut_reason = ""
    if scores[c]["score"] < 48:
        value -= 15; stable_score -= 18; high_odds_score -= 8; variable_score -= 8; cut_reason = "3착 후보 약함"
    if risk > 55:
        value -= 12; stable_score -= 20; high_odds_score -= 10; variable_score -= 13; cut_reason = "위험도 높음"
    if odds < 8:
        value -= 10; high_odds_score -= 18; variable_score -= 10; cut_reason = "배당 낮음"
    return {
        "combo": f"{a}-{b}-{c}", "first": a, "second": b, "third": c,
        "score": round(value, 2), "stable_score": round(stable_score, 2),
        "high_odds_score": round(high_odds_score, 2), "variable_score": round(variable_score, 2),
        "base_score": round(base, 2), "risk": round(risk, 1),
        "estimated_odds": odds, "expected_return_1000": int(odds * 1000), "cut_reason": cut_reason,
    }


def confidence_from_ranked(ranked: List[Dict[str, Any]]) -> float:
    if not ranked:
        return 0.0
    top = ranked[:30]
    top_avg = sum(x["score"] for x in top[:10]) / max(1, min(10, len(top)))
    spread = ranked[0]["score"] - ranked[min(len(ranked)-1, 50)]["score"] if len(ranked) > 50 else 0
    risk_avg = sum(x["risk"] for x in top[:10]) / max(1, min(10, len(top)))
    conf = top_avg * .75 + spread * .65 - risk_avg * .25
    return round(max(0, min(99, conf)), 1)


def choose_recommend_count(confidence: float, cfg: Dict[str, Any]) -> int:
    min_n = int(cfg.get("min_recommendations", 10))
    max_n = int(cfg.get("max_recommendations", 30))
    if confidence >= 85:
        return min_n
    if confidence >= 75:
        return min(max_n, 20)
    if confidence >= 65:
        return max_n
    return 0



def select_strategy_recommendations(ranked: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Pick exactly 3 buckets: 안정형 6, 고배당형 6, 변수형 6.
    The same combo is not repeated across buckets unless the race has fewer than 18 valid combos.
    """
    counts = cfg.get("strategy_counts") or {}
    wanted = {
        "stable": int(counts.get("stable", 6)),
        "high_odds": int(counts.get("high_odds", 6)),
        "variable": int(counts.get("variable", 6)),
    }
    labels = {"stable": "안정형", "high_odds": "고배당형", "variable": "변수형"}
    sort_keys = {
        "stable": lambda x: (x.get("stable_score", 0), -x.get("risk", 99), x.get("score", 0)),
        "high_odds": lambda x: (x.get("high_odds_score", 0), x.get("estimated_odds", 0), x.get("score", 0)),
        "variable": lambda x: (x.get("variable_score", 0), x.get("estimated_odds", 0), -abs(x.get("risk", 0) - 38)),
    }
    picked: Dict[str, List[Dict[str, Any]]] = {"stable": [], "high_odds": [], "variable": []}
    used = set()

    for bucket in ["stable", "high_odds", "variable"]:
        candidates = sorted(ranked, key=sort_keys[bucket], reverse=True)
        for item in candidates:
            if len(picked[bucket]) >= wanted[bucket]:
                break
            if item["combo"] in used:
                continue
            # 안정형은 과도한 위험 제외, 고배당/변수형은 완화
            if bucket == "stable" and item.get("risk", 0) > 52:
                continue
            if bucket == "high_odds" and item.get("estimated_odds", 0) < float(cfg.get("target_min_odds", 30)):
                continue
            copied = dict(item)
            copied["strategy"] = labels[bucket]
            copied["strategy_key"] = bucket
            picked[bucket].append(copied)
            used.add(item["combo"])

    # 데이터가 부족하거나 조건이 너무 엄격하면 남은 수량은 전체 상위에서 채움. 그래도 중복은 금지.
    for bucket in ["stable", "high_odds", "variable"]:
        for item in sorted(ranked, key=sort_keys[bucket], reverse=True):
            if len(picked[bucket]) >= wanted[bucket]:
                break
            if item["combo"] in used:
                continue
            copied = dict(item)
            copied["strategy"] = labels[bucket]
            copied["strategy_key"] = bucket
            picked[bucket].append(copied)
            used.add(item["combo"])
    return picked


def flatten_strategy_recommendations(strategy_recs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key in ["stable", "high_odds", "variable"]:
        out.extend(strategy_recs.get(key, []))
    return out

def analyze_race(race: Dict[str, Any], cfg: Optional[Dict[str, Any]] = None, api_results: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    if api_results is None:
        api_results = fetch_enabled_apis(cfg, race=race)
    horse_count = int(race.get("horse_count") or cfg.get("default_horse_count", 12))
    horse_numbers = extract_horse_numbers(api_results, horse_count)
    combos = generate_triple_combos(horse_numbers)
    scores = build_horse_scores(horse_numbers, api_results, race)
    ranked = [score_combo(c, scores, float(cfg.get("target_min_odds", 30))) for c in combos]
    ranked.sort(key=lambda x: (x["score"], x["estimated_odds"]), reverse=True)
    conf = confidence_from_ranked(ranked)
    # 형 요청: 한 경주당 안정형 6장 + 고배당형 6장 + 변수형 6장 = 총 18장 고정
    strategy_recommendations = select_strategy_recommendations(ranked, cfg)
    recommendations = flatten_strategy_recommendations(strategy_recommendations)
    rec_count = len(recommendations)
    stake = int(cfg.get("stake_per_combo", 1000))
    result = {
        "analyzed_at": now_kst().strftime("%Y-%m-%d %H:%M:%S KST"),
        "race": race,
        "horse_numbers": horse_numbers,
        "horse_count": len(horse_numbers),
        "total_combos": len(combos),
        "confidence": conf,
        "recommend_count": len(recommendations),
        "strategy_recommendations": strategy_recommendations,
        "stake_per_combo": stake,
        "budget_1000": len(recommendations) * stake,
        "status": "18장 추천 준비" if len(recommendations) == 18 else ("추천 부족" if recommendations else "구매 보류"),
        "recommendations": recommendations,
        "top_all": ranked[:100],
        "horse_scores": list(scores.values()),
        "api_status": [{"name": x.get("name"), "ok": x.get("ok"), "status": x.get("status"), "rows": len(x.get("rows", [])), "error": x.get("error", "")} for x in api_results],
    }
    safe_json_save(RESULT_CACHE_PATH, result)
    append_hub_history(result)
    try_save_google_sheet(result)
    return result


def append_hub_history(result: Dict[str, Any]) -> None:
    race = result.get("race", {})
    recs = result.get("recommendations", [])
    row = {
        "analyzed_at": result.get("analyzed_at"),
        "date": race.get("date") or today_str(),
        "place": race.get("place"),
        "race_no": race.get("race_no"),
        "start_time": race.get("start_time"),
        "horse_count": result.get("horse_count"),
        "total_combos": result.get("total_combos"),
        "confidence": result.get("confidence"),
        "recommend_count": result.get("recommend_count"),
        "budget_1000": result.get("budget_1000"),
        "status": result.get("status"),
        "top_combos": ", ".join(f"{r.get('strategy','')}-{r['combo']}" for r in recs[:30]),
    }
    exists = HUB_CSV_PATH.exists()
    with HUB_CSV_PATH.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def try_save_google_sheet(result: Dict[str, Any]) -> bool:
    """Optional. Works when Streamlit/GitHub secrets env vars are set."""
    sheet_id = os.getenv("SHEET_ID", "")
    service_json = os.getenv("SERVICE_ACCOUNT_JSON", "")
    if not sheet_id or not service_json:
        return False
    try:
        import gspread
        creds_dict = json.loads(service_json)
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open_by_key(sheet_id)
        try:
            ws = sh.worksheet("kra_hub")
        except Exception:
            ws = sh.add_worksheet(title="kra_hub", rows=2000, cols=20)
            ws.append_row(["analyzed_at", "date", "place", "race_no", "start_time", "confidence", "recommend_count", "budget_1000", "status", "top_combos"])
        race = result.get("race", {})
        ws.append_row([
            result.get("analyzed_at"), race.get("date") or today_str(), race.get("place"), race.get("race_no"), race.get("start_time"),
            result.get("confidence"), result.get("recommend_count"), result.get("budget_1000"), result.get("status"),
            ", ".join(f"{r.get('strategy','')}-{r['combo']}" for r in result.get("recommendations", [])[:30])
        ])
        return True
    except Exception:
        return False


def bootstrap_today_schedule(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    results = fetch_enabled_apis(cfg, limit=10)
    races = extract_races_from_api_results(results, cfg)
    if not races:
        races = cfg.get("manual_races") or default_manual_races()
    save_today_races(races)
    return {"saved_at": now_kst().strftime("%Y-%m-%d %H:%M:%S KST"), "race_count": len(races), "races": races, "api_status": results}


def parse_today_time(hhmm: str) -> Optional[datetime]:
    try:
        hh, mm = map(int, hhmm.split(":"))
        return now_kst().replace(hour=hh, minute=mm, second=0, microsecond=0)
    except Exception:
        return None


def due_races(races: List[Dict[str, Any]], minutes_before: int = 30, minutes_after: int = 5) -> List[Dict[str, Any]]:
    now = now_kst()
    out = []
    for r in races:
        st = parse_today_time(str(r.get("start_time", "")))
        if not st:
            continue
        if st - timedelta(minutes=minutes_before) <= now <= st + timedelta(minutes=minutes_after):
            out.append(r)
    return out


def run_due_analysis(cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    races = load_today_races(cfg)
    due = due_races(races)
    analyzed = []
    for r in due:
        analyzed.append(analyze_race(r, cfg))
    return {"checked_at": now_kst().strftime("%Y-%m-%d %H:%M:%S KST"), "due_count": len(due), "analyzed": analyzed}


def recommendations_text(result: Dict[str, Any]) -> str:
    race = result.get("race", {})
    lines = [f"{race.get('place')} {race.get('race_no')}경주 삼쌍승 18장 추천 ({result.get('analyzed_at')})"]
    lines.append(f"총 {result.get('recommend_count', 0)}장 / {result.get('stake_per_combo', 1000):,}원씩 / 합계 {result.get('budget_1000', 0):,}원")
    strategy_recs = result.get("strategy_recommendations") or {}
    order = [("stable", "안정형"), ("high_odds", "고배당형"), ("variable", "변수형")]
    for key, label in order:
        rows = strategy_recs.get(key, [])
        if not rows:
            continue
        lines.append("")
        lines.append(f"[{label} {len(rows)}장]")
        for i, r in enumerate(rows, 1):
            lines.append(f"{i}. {r['combo']} / 점수 {r['score']} / 예상배당 {r['estimated_odds']}배 / 위험 {r['risk']}")
    return "\n".join(lines)


def latest_result() -> Dict[str, Any]:
    return safe_json_load(RESULT_CACHE_PATH, {})
