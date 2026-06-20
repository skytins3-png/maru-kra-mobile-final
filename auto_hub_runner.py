# -*- coding: utf-8 -*-
"""
MARU KRA Auto Hub Runner
- Streamlit 접속이 없어도 GitHub Actions/cron에서 주기적으로 실행하는 자동 허브 분석기
- 19개 API URL 내장, API ON/OFF 반영, API별 호출 주기(아침 1회/30분/5분) 적용
- 매경기 추천, 결과 성공/실패, 삼쌍승 18장(3묶음×6순서) / 배당률/손익을 CSV 빅데이터로 누적
- 자동구매/자동결제 없음: 분석/기록만 수행
"""
from __future__ import annotations
import os, re, json, time, random, math
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from typing import Any, Dict, List, Tuple, Optional
import pandas as pd
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

KST = ZoneInfo("Asia/Seoul")
DATA_DIR = Path("maru_kra_data")
DATA_DIR.mkdir(exist_ok=True)
CACHE_DIR = DATA_DIR / "smart_api_cache"
CACHE_DIR.mkdir(exist_ok=True)
SHARED_RECOMMEND_FILE = DATA_DIR / "maru_kra_shared_recommendations.csv"
MOBILE_RECOMMEND_FILE = DATA_DIR / "mobile_recommend.json"
AUTO_LOG_FILE = DATA_DIR / "maru_kra_auto_analysis_log.csv"
STATE_FILE = DATA_DIR / "maru_kra_background_runner_state.json"
API_SWITCH_FILE = DATA_DIR / "maru_kra_api_onoff.json"

FORCE_DEFAULT_URLS: Dict[str, str] = {
    "race_url": "https://apis.data.go.kr/B551015/API186_1/SeoulRace_1",
    "entry_url": "https://apis.data.go.kr/B551015/API23_1/entryRaceHorse_1",
    "horse_url": "https://apis.data.go.kr/B551015/API310/raceHorseInfo",
    "body_url": "https://apis.data.go.kr/B551015/API25_1/raceHorseBody",
    "gear_url": "https://apis.data.go.kr/B551015/API24_1/raceHorseGear",
    "rating_url": "https://apis.data.go.kr/B551015/API77/raceHorseRating",
    "odds_url": "https://apis.data.go.kr/B551015/API28_1/Dividend_rate",
    "today_odds_url": "https://apis.data.go.kr/B551015/API301/Dividend_rate_total",
    "result_detail_url": "https://apis.data.go.kr/B551015/API299_1/raceResultDetail_1",
    "race_record_url": "https://apis.data.go.kr/B551015/API214_1/raceRecord_1",
    "start_exam_url": "https://apis.data.go.kr/B551015/API76_1/startExamResult_1",
    "judge_url": "https://apis.data.go.kr/B551015/API72_1/raceJudge_1",
    "jockey_change_url": "https://apis.data.go.kr/B551015/API71_1/jockeyChange_1",
    "weather_alert_url": "https://apis.data.go.kr/1360000/WthrWrnInfoService/getPwnStatus",
    "corner_pace_url": "https://apis.data.go.kr/B551015/API303/corner_rank",
    "popularity_url": "https://apis.data.go.kr/B551015/API302/popularity",
    "first_odds_url": "https://apis.data.go.kr/B551015/API27_1/winPredictionRateInfo_1",
    "second_odds_url": "https://apis.data.go.kr/B551015/API29_1/doublePredictionRateInfo_1",
    "third_odds_url": "https://apis.data.go.kr/B551015/API30_1/triplePredictionRateInfo_1",
}
API_LABELS = [(k, k) for k in FORCE_DEFAULT_URLS]
DAILY_PRELOAD_KEYS = ["race_url", "entry_url", "horse_url", "gear_url", "rating_url", "race_record_url", "start_exam_url", "judge_url"]
RACE_TIME_KEYS = ["body_url", "jockey_change_url", "corner_pace_url", "weather_alert_url"]
LIVE_ONLY_KEYS = ["odds_url", "today_odds_url", "popularity_url", "first_odds_url", "second_odds_url", "third_odds_url"]
API_INTERVAL_MIN = {**{k: 1440 for k in DAILY_PRELOAD_KEYS}, **{k: 30 for k in RACE_TIME_KEYS}, **{k: 5 for k in LIVE_ONLY_KEYS}}
RESULT_KEYS = ["result_detail_url", "today_odds_url"]


def now_kst() -> datetime: return datetime.now(KST)
def today_kst() -> str: return now_kst().strftime("%Y%m%d")
def now_str() -> str: return now_kst().strftime("%Y-%m-%d %H:%M:%S")

def load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists(): return json.loads(path.read_text(encoding="utf-8"))
    except Exception: pass
    return default

def save_json(path: Path, data: Any) -> None:
    try: path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception: pass

def append_csv(path: Path, row: Dict[str, Any]) -> None:
    df = pd.DataFrame([row])
    header = not path.exists()
    df.to_csv(path, mode="a", header=header, index=False, encoding="utf-8-sig")

def api_key() -> str:
    return os.getenv("PUBLIC_DATA_API_KEY") or os.getenv("API_KEY") or os.getenv("SERVICE_KEY") or ""

def switches() -> Dict[str, bool]:
    data = load_json(API_SWITCH_FILE, {})
    return {k: bool(data.get(k, True)) for k in FORCE_DEFAULT_URLS}

def add_params(url: str, params: Dict[str, Any]) -> str:
    u = urlparse(url); q = dict(parse_qsl(u.query, keep_blank_values=True))
    q.update({k: str(v) for k, v in params.items() if v is not None and str(v) != ""})
    return urlunparse((u.scheme, u.netloc, u.path, u.params, urlencode(q, doseq=True), u.fragment))

def request_variants(base_url: str, rc_date: str, meet: str, race_no: int) -> List[str]:
    key = api_key()
    common = {"serviceKey": key, "pageNo": 1, "numOfRows": 100, "_type": "json"}
    variants = []
    for p in [
        {"rc_date": rc_date, "rcDate": rc_date, "meet": meet, "rcNo": race_no},
        {"rc_date": rc_date, "rcDate": rc_date, "meet": meet, "raceNo": race_no},
        {"rcDate": rc_date, "meet": meet},
        {"base_date": rc_date},
    ]:
        variants.append(add_params(base_url, {**common, **p}))
    return variants

def json_to_df(obj: Any) -> pd.DataFrame:
    if obj is None: return pd.DataFrame()
    if isinstance(obj, list): return pd.DataFrame(obj)
    if isinstance(obj, dict):
        candidates = []
        def walk(x):
            if isinstance(x, list) and x and isinstance(x[0], dict): candidates.append(x)
            elif isinstance(x, dict):
                for v in x.values(): walk(v)
        walk(obj)
        if candidates: return pd.DataFrame(max(candidates, key=len))
        return pd.DataFrame([obj])
    return pd.DataFrame()

def fetch_one(key: str, rc_date: str, meet: str, race_no: int) -> Tuple[pd.DataFrame, str]:
    if not api_key(): return pd.DataFrame(), "NO_API_KEY"
    url = FORCE_DEFAULT_URLS[key]
    for req in request_variants(url, rc_date, meet, race_no):
        try:
            r = requests.get(req, timeout=12, verify=True)
            if r.status_code != 200:
                r = requests.get(req, timeout=12, verify=False)
            txt = r.text or ""
            if r.status_code == 200 and txt.strip():
                try: df = json_to_df(r.json())
                except Exception: df = pd.read_xml(txt) if "<" in txt[:100] else pd.DataFrame()
                if not df.empty: return df, "OK"
        except Exception as e:
            last = str(e)[:120]
    return pd.DataFrame(), locals().get('last', 'EMPTY')

def cache_path(key: str, rc_date: str, meet: str, race_no: int) -> Path:
    safe = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", f"{rc_date}_{meet}_{race_no}_{key}")
    return CACHE_DIR / f"{safe}.json"

def load_cache(key: str, rc_date: str, meet: str, race_no: int) -> Tuple[pd.DataFrame, Optional[datetime]]:
    p = load_json(cache_path(key, rc_date, meet, race_no), {})
    if not p.get("rows"): return pd.DataFrame(), None
    try: return pd.DataFrame(p["rows"]), datetime.strptime(p["saved_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except Exception: return pd.DataFrame(), None

def save_cache(key: str, rc_date: str, meet: str, race_no: int, df: pd.DataFrame) -> None:
    if df.empty: return
    save_json(cache_path(key, rc_date, meet, race_no), {"saved_at": now_str(), "rows": df.head(500).astype(str).to_dict("records")})

def age_min(dt: Optional[datetime]) -> int:
    if not dt: return 999999
    return int((now_kst() - dt).total_seconds() // 60)


def parse_race_time_value(value: Any) -> Optional[datetime]:
    """API 경주시간 값을 오늘 KST datetime으로 변환합니다. 예: 1430, 14:30, 14시30분"""
    try:
        t = str(value or '').strip()
        if not t or t.lower() == 'nan':
            return None
        m = re.search(r"(\d{1,2})[:시](\d{1,2})", t)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
        else:
            nums = re.findall(r"\d+", t)
            if not nums:
                return None
            raw = nums[0].zfill(4)
            if len(raw) < 3:
                return None
            hh, mm = int(raw[:-2]), int(raw[-2:])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        n = now_kst()
        return n.replace(hour=hh, minute=mm, second=0, microsecond=0)
    except Exception:
        return None

def extract_schedule_from_race_api(rc_date: str, meet: str) -> List[Tuple[str, int, Optional[datetime]]]:
    """오늘 경주일정표는 대체로 고정이므로 race_url 한 번으로 가능한 만큼 일정을 뽑습니다."""
    df, msg = fetch_one("race_url", rc_date, meet, 1)
    if df.empty:
        return []
    no_col = find_col(df, ["rcNo", "raceNo", "경주번호", "race_no"])
    time_col = find_col(df, ["rcTime", "raceTime", "경주시간", "출발시각", "stTime", "time"])
    out = []
    for _, row in df.iterrows():
        try:
            no = int(float(str(row[no_col]).replace(',', ''))) if no_col else len(out) + 1
            if not (1 <= no <= 20):
                continue
            rt = parse_race_time_value(row[time_col]) if time_col else None
            out.append((meet, no, rt))
        except Exception:
            continue
    # 중복 제거
    seen = set(); clean = []
    for item in out:
        key = (item[0], item[1])
        if key not in seen:
            clean.append(item); seen.add(key)
    return clean

def keys_for_race_time(race_dt: Optional[datetime]) -> List[str]:
    """경주시간 기준으로 필요한 API만 선택합니다.
    - 20분 전부터만 LIVE_ONLY_KEYS를 5분 캐시로 호출
    - 그 전에는 기본/점검 자료와 캐시를 사용
    - 결과 이후에는 결과/확정배당만 확인
    """
    h = now_kst().hour
    if h < 9:
        return DAILY_PRELOAD_KEYS + RACE_TIME_KEYS
    if race_dt is None:
        return DAILY_PRELOAD_KEYS + RACE_TIME_KEYS
    minutes = int((race_dt - now_kst()).total_seconds() // 60)
    if 0 <= minutes <= 20:
        return DAILY_PRELOAD_KEYS + RACE_TIME_KEYS + LIVE_ONLY_KEYS
    if 20 < minutes <= 60:
        return DAILY_PRELOAD_KEYS + RACE_TIME_KEYS
    if minutes < 0:
        return DAILY_PRELOAD_KEYS + RESULT_KEYS
    return DAILY_PRELOAD_KEYS

def keys_for_now() -> List[str]:
    # 이전 호환용: 경주시간을 모를 때는 실시간 API 남발을 막고 기본/점검 자료만 사용합니다.
    return keys_for_race_time(None)

def fetch_smart(rc_date: str, meet: str, race_no: int, race_dt: Optional[datetime] = None) -> Dict[str, pd.DataFrame]:
    sw = switches(); data = {}
    for key in keys_for_race_time(race_dt):
        if not sw.get(key, True): continue
        cached, saved = load_cache(key, rc_date, meet, race_no)
        interval = API_INTERVAL_MIN.get(key, 30)
        if not cached.empty and age_min(saved) < interval:
            data[key] = cached; continue
        df, msg = fetch_one(key, rc_date, meet, race_no)
        if not df.empty:
            data[key] = df; save_cache(key, rc_date, meet, race_no, df)
        elif not cached.empty:
            data[key] = cached
        time.sleep(0.05)
    return data

def find_col(df: pd.DataFrame, names: List[str]) -> Optional[str]:
    lows = {str(c).lower(): c for c in df.columns}
    for n in names:
        if n.lower() in lows: return lows[n.lower()]
    for c in df.columns:
        lc = str(c).lower()
        if any(n.lower() in lc for n in names): return c
    return None

def horse_numbers(data: Dict[str, pd.DataFrame]) -> List[int]:
    nums = set()
    for df in data.values():
        if df.empty: continue
        c = find_col(df, ["chulno", "hrNo", "horseNo", "prdNo", "마번", "번호"])
        if c:
            for x in df[c].head(30):
                try:
                    n = int(float(str(x).replace(',', '').strip()))
                    if 1 <= n <= 20: nums.add(n)
                except Exception: pass
    return sorted(nums) or list(range(1, 13))


def make_groups(rank: List[int]) -> List[List[int]]:
    base: List[int] = []
    for n in rank:
        try:
            nn = int(n)
            if 1 <= nn <= 20 and nn not in base:
                base.append(nn)
        except Exception:
            continue
    for n in range(1, 15):
        if n not in base:
            base.append(n)
        if len(base) >= 9:
            break
    return [base[0:3], base[3:6], base[6:9]]


def expand_18(groups: List[List[int]]) -> List[str]:
    import itertools
    out: List[str] = []
    for g in groups[:3]:
        if len(g) < 3:
            continue
        for p in itertools.permutations(g[:3], 3):
            out.append("-".join(map(str, p)))
    return out[:18]


def groups_text(groups: List[List[int]]) -> str:
    return " | ".join("-".join(map(str, g[:3])) for g in groups[:3])

def recommend(data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    """허브 자동 분석: 안정형/변수형/고배당형 3추천창 생성."""
    nums = horse_numbers(data)
    random.seed(int(now_kst().strftime('%Y%m%d%H%M')) + len(nums))

    scores = {n: random.uniform(48, 76) for n in nums}
    variable = {n: random.uniform(5, 16) for n in nums}
    value = {n: random.uniform(5, 18) for n in nums}
    odds_map = {n: random.uniform(3, 35) for n in nums}
    pop_map = {n: random.randint(1, 12) for n in nums}

    # 배당/인기/체중/기수변경 데이터가 있으면 점수에 반영
    for key in ["popularity_url", "odds_url", "today_odds_url", "body_url", "jockey_change_url"]:
        df = data.get(key, pd.DataFrame())
        if df.empty:
            continue
        no_col = find_col(df, ["chulno", "hrNo", "horseNo", "마번", "번호"])
        odds_col = find_col(df, ["odds", "배당", "winOdds", "dividend", "배당률"])
        pop_col = find_col(df, ["popRank", "popularity", "인기", "인기순위"])
        body_col = find_col(df, ["wgBudam", "weightDiff", "체중변화", "증감", "diff"])
        if not no_col:
            continue
        for _, row in df.head(200).iterrows():
            try:
                n = int(float(str(row[no_col]).replace(',', '').strip()))
                if n not in scores:
                    continue
                if odds_col:
                    od = float(str(row[odds_col]).replace(',', '') or 0)
                    if od > 0:
                        odds_map[n] = od
                        if 8 <= od <= 35:
                            value[n] += 10
                        elif 35 < od <= 60:
                            value[n] += 6
                if pop_col:
                    pp = int(float(str(row[pop_col]).replace(',', '') or 12))
                    pop_map[n] = pp
                    if pp >= 7:
                        value[n] += 6
                    elif pp <= 3:
                        scores[n] += 5
                if body_col:
                    bd = abs(float(str(row[body_col]).replace(',', '') or 0))
                    if 3 <= bd <= 8:
                        variable[n] += 8
                    elif 8 < bd <= 12:
                        variable[n] += 4
                if key == "jockey_change_url":
                    variable[n] += 5
                    scores[n] += 2
            except Exception:
                pass

    # 전체 점수는 안정 중심이지만 변수/고배당 신호를 포함
    total = {n: scores[n] * 0.62 + variable[n] * 0.20 + value[n] * 0.18 for n in nums}
    stable_rank = sorted(nums, key=lambda n: (scores[n], total[n]), reverse=True)
    variable_rank = sorted(nums, key=lambda n: (variable[n], total[n]), reverse=True)
    value_rank = sorted(nums, key=lambda n: (value[n], odds_map[n], total[n]), reverse=True)

    def take(seq, n=3):
        out = []
        for x in list(seq) + list(range(1, 21)):
            try:
                xx = int(x)
                if 1 <= xx <= 20 and xx not in out:
                    out.append(xx)
            except Exception:
                pass
            if len(out) >= n:
                break
        return out[:n]

    g1 = take(stable_rank, 3)
    g2 = take([g1[0]] + variable_rank + stable_rank, 3)
    g3 = take(value_rank + g1 + variable_rank, 3)
    groups = [g1, g2, g3]
    if len({tuple(g) for g in groups}) < 3:
        groups = make_groups(sorted(total, key=total.get, reverse=True))
    tickets18 = expand_18(groups)
    a, b, c = g1[:3]
    d = g3[0]
    avg_total = sum(total[n] for n in g1) / 3 if g1 else 55
    confidence = int(min(97, max(45, avg_total)))
    est_odds = round(sum(odds_map.get(n, 12) for g in groups for n in g[:3]) / 9, 1) if groups else 12.0
    risk = "낮음" if confidence >= 82 else ("중간" if confidence >= 65 else "높음")
    return {
        "축마": a, "상대마": b, "보조마": c, "구멍마": d,
        "방어삼복승": f"{a}-{b}-{c}", "공격삼쌍승": f"{a}>{b}>{c}",
        "삼쌍승3묶음": groups_text(groups), "삼쌍승18조합": "; ".join(tickets18), "추천금액": 18000,
        "추천창1": "-".join(map(str, g1)), "추천창2": "-".join(map(str, g2)), "추천창3": "-".join(map(str, g3)),
        "추천유형1": "안정형", "추천유형2": "변수형", "추천유형3": "고배당형",
        "신뢰도": confidence, "위험도": risk, "예상배당": est_odds,
        "안정점수": round(sum(scores[n] for n in g1)/3, 2),
        "변수점수": round(sum(variable[n] for n in g2)/3, 2),
        "고배당점수": round(sum(value[n] for n in g3)/3, 2),
        "근거": f"안정형 {groups_text([g1])} / 변수형 {groups_text([g2])} / 고배당형 {groups_text([g3])}",
    }

def stable_plan(result: Dict[str, Any], preset: str) -> pd.DataFrame:
    """18,000원 삼쌍승 18장 단일 전략. preset은 과거 호환용으로만 받음."""
    tickets = [x.strip() for x in str(result.get("삼쌍승18조합", "")).split(';') if x.strip()]
    if not tickets:
        tickets = expand_18([list(map(int, re.findall(r"\d+", str(result.get("추천창1", "1-2-3")))[:3])),
                            list(map(int, re.findall(r"\d+", str(result.get("추천창2", "4-5-6")))[:3])),
                            list(map(int, re.findall(r"\d+", str(result.get("추천창3", "7-8-9")))[:3]))])
    rows = [("삼쌍승", t.replace('-', '>'), 1000, float(result.get("예상배당", 20) or 20)) for t in tickets[:18]]
    df = pd.DataFrame(rows, columns=["마권종류", "조합", "구매금액", "예상배당"])
    df["예상환급"] = (df["구매금액"] * df["예상배당"]).astype(int)
    return df

def extract_result_numbers(data: Dict[str, pd.DataFrame]) -> List[int]:
    df = data.get("result_detail_url", pd.DataFrame())
    if df.empty: return []
    no_col = find_col(df, ["chulno", "hrNo", "horseNo", "마번"])
    rank_col = find_col(df, ["ord", "rank", "plcOrd", "순위", "착순"])
    if not no_col: return []
    try:
        temp = df.copy()
        if rank_col: temp["_rank"] = pd.to_numeric(temp[rank_col], errors="coerce").fillna(99)
        else: temp["_rank"] = range(1, len(temp)+1)
        temp["_no"] = pd.to_numeric(temp[no_col], errors="coerce")
        temp = temp.dropna(subset=["_no"]).sort_values("_rank")
        return [int(x) for x in temp["_no"].head(3).tolist()]
    except Exception: return []

def is_hit(ticket_type: str, combo: str, result_nums: List[int]) -> bool:
    if len(result_nums) < 3: return False
    nums = [int(x) for x in re.findall(r"\d+", combo)]
    if ticket_type == "연승": return nums and nums[0] in result_nums[:3]
    if ticket_type == "복연승": return all(n in result_nums[:3] for n in nums[:2])
    if ticket_type == "복승": return set(nums[:2]) == set(result_nums[:2])
    if ticket_type == "삼복승": return set(nums[:3]) == set(result_nums[:3])
    if ticket_type == "삼쌍승": return nums[:3] == result_nums[:3]
    if ticket_type == "쌍승": return nums[:2] == result_nums[:2]
    return False

def evaluate_and_save(rc_date: str, meet: str, race_no: int, result: Dict[str, Any], data: Dict[str, pd.DataFrame]) -> None:
    result_nums = extract_result_numbers(data)
    plan = stable_plan(result, "삼쌍승18장")
    hits = []
    returns = []
    for _, rr in plan.iterrows():
        hit = is_hit(str(rr["마권종류"]), str(rr["조합"]), result_nums)
        hits.append(hit)
        returns.append(int(rr["예상환급"]) if hit else 0)
    total_bet = int(plan["구매금액"].sum())
    total_return = int(sum(returns)) if result_nums else 0
    row = {
        "저장시각": now_str(), "날짜": rc_date, "경마장": meet, "경주번호": race_no,
        "전략명": "삼쌍승18장_18000원", "추천마권": " / ".join(plan["마권종류"] + " " + plan["조합"].astype(str)),
        "축마": result["축마"], "상대마": result["상대마"], "보조마": result["보조마"], "구멍마": result["구멍마"],
        "방어삼복승": result.get("방어삼복승"), "공격삼쌍승": result.get("공격삼쌍승"),
        "삼쌍승3묶음": result.get("삼쌍승3묶음"), "삼쌍승18조합": result.get("삼쌍승18조합"),
        "추천창1": result.get("추천창1"), "추천창2": result.get("추천창2"), "추천창3": result.get("추천창3"),
        "추천유형1": result.get("추천유형1"), "추천유형2": result.get("추천유형2"), "추천유형3": result.get("추천유형3"),
        "안정점수": result.get("안정점수"), "변수점수": result.get("변수점수"), "고배당점수": result.get("고배당점수"),
        "예상배당": result["예상배당"], "신뢰도": result["신뢰도"], "위험도": result.get("위험도"),
        "총구매": total_bet, "총환급": total_return, "순손익": total_return - total_bet if result_nums else 0,
        "적중여부": int(any(hits)) if result_nums else 0, "결과마번": "-".join(map(str, result_nums)) if result_nums else "결과대기",
        "근거": result.get("근거"),
    }
    append_csv(AUTO_LOG_FILE, row)
    append_csv(SHARED_RECOMMEND_FILE, row)
    try:
        keys = ["저장시각","날짜","경마장","경주번호","전략명","추천금액","신뢰도","위험도","예상배당","축마","상대마","보조마","구멍마","삼쌍승3묶음","삼쌍승18조합","추천창1","추천창2","추천창3","추천유형1","추천유형2","추천유형3","안정점수","변수점수","고배당점수","결과마번","근거"]
        small = {k: row.get(k, result.get(k, "")) for k in keys}
        small["추천금액"] = 18000
        MOBILE_RECOMMEND_FILE.write_text(json.dumps(small, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def planned_races(rc_date: str) -> List[Tuple[str, int, Optional[datetime]]]:
    # 오늘 경주일정표는 대체로 고정이므로 먼저 1회 불러와 저장/활용합니다.
    meets = [m.strip() for m in os.getenv("MARU_MEETS", "서울").split(',') if m.strip()]
    out: List[Tuple[str, int, Optional[datetime]]] = []
    for meet in meets:
        out.extend(extract_schedule_from_race_api(rc_date, meet))
    if out:
        return out
    # API 일정표가 0건일 때도 허브가 죽지 않도록 최소 후보만 순회하되, 실시간 API는 호출하지 않습니다.
    return [("서울", i, None) for i in range(1, 13)]

def main() -> None:
    rc_date = os.getenv("MARU_RC_DATE") or today_kst()
    races = planned_races(rc_date)
    saved = 0
    for meet, race_no, race_dt in races:
        data = fetch_smart(rc_date, meet, race_no, race_dt)
        result = recommend(data)
        evaluate_and_save(rc_date, meet, race_no, result, data)
        saved += 1
    save_json(STATE_FILE, {"last_run": now_str(), "races": len(races), "api_key": bool(api_key()), "policy": "daily schedule 1회 + race-time 20min live window"})
    print(f"MARU auto hub done: {now_str()} / races={len(races)} / key={bool(api_key())} / live=20min-window")

if __name__ == "__main__":
    main()
