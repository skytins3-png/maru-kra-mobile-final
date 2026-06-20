# -*- coding: utf-8 -*-
"""
MARU KRA Mobile Final App
- 경마 공공데이터 API 수집/분석/추천 대시보드
- 자동 마권 구매/자동 결제 기능 없음
- 사용자가 직접 확인 후 KRA 구매 페이지로 이동하는 수동 구조
"""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import requests
import streamlit as st

APP_NAME = "MARU KRA 실시간 분석"
CONFIG_DIR = ".maru_kra"
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
HISTORY_PATH = os.path.join(CONFIG_DIR, "history.csv")
KST = timezone(timedelta(hours=9))

# 공식 구매/이용 페이지는 사용자가 직접 확인하고 진행하는 수동 링크입니다.
KRA_MAIN_URL = "https://www.kra.co.kr/"
KRA_BETTING_URL = "https://www.kra.co.kr/"

DEFAULT_API_URLS = [
    {"name": "경마경주정보", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/race?serviceKey={serviceKey}&pageNo=1&numOfRows=100&_type=json&meet={meet}&rcDate={today}"},
    {"name": "RC경마경주정보", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/rcRace?serviceKey={serviceKey}&pageNo=1&numOfRows=100&_type=json&meet={meet}&rcDate={today}"},
    {"name": "출전표/엔트리", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/entry?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}&rcDate={today}"},
    {"name": "경주마정보", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/horse?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}"},
    {"name": "경주마정보_영문추가", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/horseEng?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}"},
    {"name": "기수정보", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/jockey?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}"},
    {"name": "조교사정보", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/trainer?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}"},
    {"name": "마주정보", "enabled": False, "url": "https://apis.data.go.kr/B551015/API310/owner?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}"},
    {"name": "경주결과종합", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/result?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}&rcDate={today}"},
    {"name": "확정배당율종합", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/dividend?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}&rcDate={today}"},
    {"name": "코너별통과순위_주로빠르기", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/corner?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}&rcDate={today}"},
    {"name": "경마매출정보", "enabled": False, "url": "https://apis.data.go.kr/B551015/API310/sales?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}&rcDate={today}"},
    {"name": "마체중정보", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/weight?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}&rcDate={today}"},
    {"name": "출전마최근성적", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/recent?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}&rcDate={today}"},
    {"name": "경주마혈통", "enabled": False, "url": "https://apis.data.go.kr/B551015/API310/pedigree?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}"},
    {"name": "주로상태", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/track?serviceKey={serviceKey}&pageNo=1&numOfRows=300&_type=json&meet={meet}&rcDate={today}"},
    {"name": "날씨정보", "enabled": True, "url": "https://apis.data.go.kr/B551015/API310/weather?serviceKey={serviceKey}&pageNo=1&numOfRows=100&_type=json&meet={meet}&rcDate={today}"},
    {"name": "기상특보 조회서비스", "enabled": False, "url": "https://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList?serviceKey={serviceKey}&pageNo=1&numOfRows=100&dataType=JSON&fromTmFc={today}&toTmFc={today}"},
    {"name": "전국 승마장 정보", "enabled": False, "url": "https://apis.data.go.kr/B551015/API310/ridingClub?serviceKey={serviceKey}&pageNo=1&numOfRows=100&_type=json"},
]

MEET_MAP = {
    "서울": "1",
    "제주": "2",
    "부산경남": "3",
}

BET_TYPES = ["복승 참고", "쌍승 참고", "삼복승 참고", "고배당 관찰"]

st.set_page_config(page_title=APP_NAME, page_icon="🏇", layout="wide", initial_sidebar_state="collapsed")

CSS = """
<style>
:root { --bg:#0f172a; --card:#111827; --soft:#1f2937; --txt:#f8fafc; --muted:#cbd5e1; --accent:#facc15; --good:#22c55e; --warn:#fb923c; --bad:#ef4444; }
[data-testid="stAppViewContainer"] { background: linear-gradient(180deg, #0f172a 0%, #111827 55%, #020617 100%); }
[data-testid="stHeader"] { background: rgba(15, 23, 42, 0); }
.block-container { padding-top: 1.0rem; padding-bottom: 2rem; max-width: 1100px; }
.hero { border-radius: 22px; padding: 22px; background: linear-gradient(135deg, rgba(250,204,21,.23), rgba(59,130,246,.12)); border: 1px solid rgba(250,204,21,.35); }
.hero h1 { font-size: clamp(2.0rem, 7vw, 4.2rem); margin:0; color:#fff; letter-spacing:-1px; }
.hero p { color:#e5e7eb; font-size: 1.05rem; margin:.4rem 0 0 0; }
.big-card { padding: 20px; border-radius: 22px; background: rgba(17,24,39,.9); border: 1px solid rgba(255,255,255,.10); box-shadow: 0 12px 40px rgba(0,0,0,.25); }
.pick { font-size: clamp(2.6rem, 11vw, 5.5rem); color: #facc15; font-weight: 900; line-height:1; letter-spacing:-2px; }
.sub { color:#cbd5e1; font-size:1rem; }
.badge { display:inline-block; padding: 6px 12px; border-radius: 999px; background:rgba(250,204,21,.16); border:1px solid rgba(250,204,21,.30); color:#fde68a; font-weight:700; margin:3px; }
.green { color:#86efac; font-weight:800; }
.orange { color:#fdba74; font-weight:800; }
.red { color:#fca5a5; font-weight:800; }
.small-note { color:#cbd5e1; font-size:.92rem; }
.stButton > button { border-radius: 14px; min-height: 48px; font-weight: 800; }
[data-testid="stMetricValue"] { color:#fff; font-size:2rem; }
[data-testid="stMetricLabel"] { color:#cbd5e1; }
div[data-testid="stDataFrame"] { border-radius: 16px; overflow:hidden; }
hr { border-color: rgba(255,255,255,.13); }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def now_kst() -> datetime:
    return datetime.now(KST)


def today_str() -> str:
    return now_kst().strftime("%Y%m%d")


def ensure_dir() -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_config() -> Dict[str, Any]:
    ensure_dir()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "api_urls" not in cfg:
                cfg["api_urls"] = DEFAULT_API_URLS
            return cfg
        except Exception:
            pass
    return {
        "service_key": "",
        "meet": "서울",
        "api_urls": DEFAULT_API_URLS,
        "refresh_sec": 0,
        "risk_mode": "균형형",
    }


def save_config(cfg: Dict[str, Any]) -> None:
    ensure_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def mask_key(key: str) -> str:
    if not key:
        return "미저장"
    if len(key) <= 10:
        return "저장됨"
    return key[:4] + "***" + key[-4:]


def safe_float(v: Any, default: float = np.nan) -> float:
    if v is None:
        return default
    try:
        s = str(v).strip().replace(",", "")
        if s in ["", "-", "nan", "None"]:
            return default
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else default
    except Exception:
        return default


def safe_int(v: Any, default: int = 0) -> int:
    x = safe_float(v, np.nan)
    if np.isnan(x):
        return default
    return int(x)


def extract_items(obj: Any) -> List[Dict[str, Any]]:
    """공공데이터 JSON 구조가 제각각이어도 item 리스트를 최대한 찾아냅니다."""
    if obj is None:
        return []
    if isinstance(obj, list):
        out = []
        for x in obj:
            if isinstance(x, dict):
                out.append(x)
        return out
    if not isinstance(obj, dict):
        return []

    candidates = []
    def walk(x: Any):
        if isinstance(x, dict):
            for k, v in x.items():
                if k.lower() in ["item", "items"]:
                    candidates.append(v)
                walk(v)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(obj)

    for c in candidates:
        if isinstance(c, list):
            return [i for i in c if isinstance(i, dict)]
        if isinstance(c, dict):
            return [c]
    # fallback: dict 자체가 행처럼 보이면 1건 처리
    if any(k.lower() in obj for k in ["rcno", "hrno", "hrname", "chulno", "jkname"]):
        return [obj]
    return []


def build_url(template: str, service_key: str, meet: str) -> str:
    meet_code = MEET_MAP.get(meet, "1")
    replacements = {
        "{serviceKey}": quote_plus(service_key),
        "{service_key}": quote_plus(service_key),
        "{today}": today_str(),
        "{date}": today_str(),
        "{meet}": meet_code,
        "{meetName}": quote_plus(meet),
        "{kst}": now_kst().strftime("%Y%m%d%H%M%S"),
    }
    url = template
    for k, v in replacements.items():
        url = url.replace(k, v)
    return url


def fetch_one(api: Dict[str, Any], service_key: str, meet: str, timeout: int = 10) -> Tuple[str, List[Dict[str, Any]], str]:
    name = api.get("name", "API")
    if not api.get("enabled", True):
        return name, [], "OFF"
    template = api.get("url", "")
    if not template:
        return name, [], "URL 없음"
    try:
        url = build_url(template, service_key, meet)
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "MARU-KRA-Mobile/1.0"})
        if r.status_code != 200:
            return name, [], f"HTTP {r.status_code}"
        text = r.text.strip()
        try:
            data = r.json()
        except Exception:
            # XML이나 오류문이면 일부 메시지만 반환
            return name, [], "JSON 아님: " + text[:80]
        items = extract_items(data)
        return name, items, f"OK {len(items)}건"
    except requests.Timeout:
        return name, [], "시간초과"
    except Exception as e:
        return name, [], f"오류: {str(e)[:80]}"


def fetch_all(cfg: Dict[str, Any]) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame]:
    service_key = cfg.get("service_key", "")
    meet = cfg.get("meet", "서울")
    dfs: Dict[str, pd.DataFrame] = {}
    logs = []
    for api in cfg.get("api_urls", DEFAULT_API_URLS):
        name, items, status = fetch_one(api, service_key, meet)
        df = pd.DataFrame(items)
        if not df.empty:
            df["_source"] = name
        dfs[name] = df
        logs.append({"API": name, "상태": status, "건수": len(df), "시간": now_kst().strftime("%H:%M:%S")})
    return dfs, pd.DataFrame(logs)


def find_col(df: pd.DataFrame, names: List[str]) -> str:
    if df is None or df.empty:
        return ""
    lower_map = {c.lower(): c for c in df.columns}
    for n in names:
        if n in df.columns:
            return n
        if n.lower() in lower_map:
            return lower_map[n.lower()]
    for c in df.columns:
        cl = c.lower()
        for n in names:
            if n.lower() in cl:
                return c
    return ""


def normalize_entries(dfs: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    # 출전표가 있으면 우선 사용, 없으면 모든 DF에서 말/기수 비슷한 컬럼을 가진 것 합치기
    preferred_names = ["출전표/엔트리", "경마경주정보", "RC경마경주정보"]
    frames = []
    for name in preferred_names:
        df = dfs.get(name, pd.DataFrame())
        if not df.empty:
            frames.append(df.copy())
    if not frames:
        for _, df in dfs.items():
            if not df.empty:
                hr_col = find_col(df, ["hrName", "hrname", "horseName", "말명", "마명"])
                if hr_col:
                    frames.append(df.copy())
    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True, sort=False).drop_duplicates()
    rc_col = find_col(raw, ["rcNo", "rcno", "raceNo", "경주번호"])
    chul_col = find_col(raw, ["chulNo", "chulno", "gate", "번호", "마번"])
    hr_col = find_col(raw, ["hrName", "hrname", "horseName", "말명", "마명"])
    jk_col = find_col(raw, ["jkName", "jkname", "jockey", "기수명", "기수"])
    tr_col = find_col(raw, ["trName", "trname", "trainer", "조교사"])
    age_col = find_col(raw, ["age", "hrAge", "연령", "나이"])
    wg_col = find_col(raw, ["wgBudam", "weight", "중량", "부담중량"])
    rc_time_col = find_col(raw, ["rcTime", "rctime", "raceTime", "경주시간", "시간"])
    dist_col = find_col(raw, ["rcDist", "distance", "거리"])
    odds_col = find_col(raw, ["winOdds", "plcOdds", "odds", "배당", "배당률"])
    rank_col = find_col(raw, ["ord", "rank", "recentRank", "순위", "착순"])

    n = len(raw)
    out = pd.DataFrame()
    out["경주"] = raw[rc_col].apply(lambda x: safe_int(x, 1)) if rc_col else 1
    out["마번"] = raw[chul_col].apply(lambda x: safe_int(x, 0)) if chul_col else np.arange(1, n + 1)
    out["말이름"] = raw[hr_col].astype(str) if hr_col else [f"출전마{i}" for i in range(1, n + 1)]
    out["기수"] = raw[jk_col].astype(str) if jk_col else "미확인"
    out["조교사"] = raw[tr_col].astype(str) if tr_col else "미확인"
    out["나이"] = raw[age_col].apply(lambda x: safe_int(x, 4)) if age_col else 4
    out["부담중량"] = raw[wg_col].apply(lambda x: safe_float(x, 55.0)) if wg_col else 55.0
    out["경주시간"] = raw[rc_time_col].astype(str) if rc_time_col else "시간미정"
    out["거리"] = raw[dist_col].apply(lambda x: safe_int(x, 1200)) if dist_col else 1200
    out["배당"] = raw[odds_col].apply(lambda x: safe_float(x, np.nan)) if odds_col else np.nan
    out["최근순위"] = raw[rank_col].apply(lambda x: safe_float(x, np.nan)) if rank_col else np.nan
    out = out.drop_duplicates(subset=["경주", "마번", "말이름"], keep="first")
    out = out[out["마번"] > 0]
    if out.empty:
        return pd.DataFrame()
    return out.sort_values(["경주", "마번"]).reset_index(drop=True)


def score_entries(entries: pd.DataFrame, risk_mode: str = "균형형") -> pd.DataFrame:
    if entries.empty:
        return entries
    df = entries.copy()
    # 기본 스코어: 실제 데이터 컬럼이 부족해도 앱이 죽지 않도록 안전 계산
    gate = df["마번"].astype(float)
    age = df["나이"].astype(float).replace(0, 4)
    weight = df["부담중량"].astype(float).replace(0, 55)
    odds = df["배당"].astype(float)
    recent = df["최근순위"].astype(float)

    gate_score = 100 - (gate.sub(6).abs() * 4).clip(0, 35)
    age_score = 100 - (age.sub(4.5).abs() * 8).clip(0, 40)
    weight_score = 100 - (weight.sub(54.5).abs() * 4).clip(0, 35)
    recent_score = np.where(recent.notna(), 100 - ((recent.clip(1, 12) - 1) * 7), 62)
    odds_score = np.where(odds.notna(), 100 - np.log1p(odds.clip(1, 80)) * 13, 62)
    value_score = np.where(odds.notna(), np.log1p(odds.clip(1, 80)) * 22 + 42, 60)

    if risk_mode == "안정형":
        total = gate_score * .18 + age_score * .13 + weight_score * .14 + recent_score * .32 + odds_score * .23
    elif risk_mode == "고배당형":
        total = gate_score * .12 + age_score * .10 + weight_score * .10 + recent_score * .23 + odds_score * .10 + value_score * .35
    else:
        total = gate_score * .16 + age_score * .12 + weight_score * .12 + recent_score * .30 + odds_score * .16 + value_score * .14

    # 같은 말명/기수명이 있으면 아주 약간 안정 보정. 실제 통계가 없을 때 중복 노이즈 방지 정도.
    df["AI점수"] = np.round(np.clip(total, 0, 99), 1)
    df["안정성"] = np.round((recent_score * .45 + odds_score * .25 + gate_score * .20 + weight_score * .10).clip(0, 99), 1)
    df["배당매력"] = np.round(value_score.clip(0, 99), 1)
    df["위험도"] = pd.cut(df["AI점수"], bins=[-1, 60, 75, 86, 100], labels=["높음", "보통", "낮음", "매우낮음"])
    df["근거"] = df.apply(make_reason, axis=1)
    return df.sort_values(["경주", "AI점수"], ascending=[True, False]).reset_index(drop=True)


def make_reason(row: pd.Series) -> str:
    reasons = []
    if row.get("AI점수", 0) >= 85:
        reasons.append("종합점수 상위")
    if row.get("안정성", 0) >= 75:
        reasons.append("안정성 양호")
    if row.get("배당매력", 0) >= 75:
        reasons.append("배당 대비 관찰")
    if 2 <= row.get("마번", 0) <= 8:
        reasons.append("게이트 무난")
    if 3 <= row.get("나이", 0) <= 6:
        reasons.append("연령대 무난")
    return " · ".join(reasons[:4]) if reasons else "데이터 부족: 수동 확인 필요"


def make_recommendations(scored: pd.DataFrame) -> pd.DataFrame:
    if scored.empty:
        return pd.DataFrame()
    rows = []
    for rc, g in scored.groupby("경주"):
        g = g.sort_values("AI점수", ascending=False).head(6)
        nums = g["마번"].astype(int).tolist()
        names = g["말이름"].astype(str).tolist()
        if len(nums) >= 2:
            rows.append({"경주": rc, "유형": "복승 참고", "조합": f"{nums[0]} - {nums[1]}", "말": f"{names[0]} / {names[1]}", "신뢰": round(g["AI점수"].head(2).mean(), 1), "설명": "상위 2두 중심. 실제 배당/출전취소 확인 필수"})
        if len(nums) >= 3:
            rows.append({"경주": rc, "유형": "삼복승 참고", "조합": f"{nums[0]} - {nums[1]} - {nums[2]}", "말": f"{names[0]} / {names[1]} / {names[2]}", "신뢰": round(g["AI점수"].head(3).mean(), 1), "설명": "상위권 3두 묶음. 무리한 금액 금지"})
        value = g.sort_values(["배당매력", "AI점수"], ascending=False).head(3)
        if len(value) >= 2:
            vnums = value["마번"].astype(int).tolist()
            vnames = value["말이름"].astype(str).tolist()
            rows.append({"경주": rc, "유형": "고배당 관찰", "조합": " - ".join(map(str, vnums[:3])), "말": " / ".join(vnames[:3]), "신뢰": round(value["AI점수"].head(3).mean(), 1), "설명": "배당 매력 후보. 위험도 높을 수 있음"})
    return pd.DataFrame(rows).sort_values(["경주", "신뢰"], ascending=[True, False]).reset_index(drop=True)


def save_history(reco: pd.DataFrame, scored: pd.DataFrame) -> None:
    ensure_dir()
    if reco.empty:
        return
    hist = reco.copy()
    hist["저장시간KST"] = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    hist["상위AI점수"] = scored["AI점수"].max() if not scored.empty else np.nan
    if os.path.exists(HISTORY_PATH):
        old = pd.read_csv(HISTORY_PATH)
        hist = pd.concat([old, hist], ignore_index=True)
    hist.tail(2000).to_csv(HISTORY_PATH, index=False, encoding="utf-8-sig")


def read_history() -> pd.DataFrame:
    if os.path.exists(HISTORY_PATH):
        try:
            return pd.read_csv(HISTORY_PATH)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def demo_data() -> pd.DataFrame:
    names = ["마루번개", "청풍질주", "백두스타", "계양돌풍", "한강불꽃", "스카이킹", "동해바람", "황금질주", "태양마루", "블루레이서"]
    jockeys = ["김기수", "이기수", "박기수", "최기수", "정기수", "오기수", "강기수", "윤기수", "한기수", "서기수"]
    rows = []
    for rc in [1, 2, 3]:
        for i in range(1, 11):
            rows.append({
                "경주": rc,
                "마번": i,
                "말이름": names[i - 1],
                "기수": jockeys[i - 1],
                "조교사": "미리보기",
                "나이": 3 + (i % 5),
                "부담중량": 52 + (i % 7),
                "경주시간": f"{11 + rc}:{(i * 3) % 60:02d}",
                "거리": 1000 + rc * 200,
                "배당": round(1.6 + i * 1.35 + rc * .7, 1),
                "최근순위": (i % 7) + 1,
            })
    return pd.DataFrame(rows)


def render_top(scored: pd.DataFrame, reco: pd.DataFrame, logs: pd.DataFrame):
    st.markdown(f"""
    <div class='hero'>
      <h1>🏇 {APP_NAME}</h1>
      <p>한국시간 {now_kst().strftime('%Y-%m-%d %H:%M:%S')} · 분석은 참고용, 구매는 반드시 본인 수동 확인</p>
    </div>
    """, unsafe_allow_html=True)
    st.write("")
    if reco.empty:
        st.warning("아직 추천 조합이 없습니다. API 키/URL/경마장/날짜를 확인하거나 미리보기 데이터를 켜세요.")
        return
    top = reco.iloc[0]
    c1, c2 = st.columns([1.5, 1])
    with c1:
        st.markdown("<div class='big-card'>", unsafe_allow_html=True)
        st.markdown(f"<span class='badge'>오늘의 강력 추천</span><span class='badge'>{top['유형']}</span>", unsafe_allow_html=True)
        st.markdown(f"<div class='sub'>제{top['경주']}경주 · 신뢰 {top['신뢰']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='pick'>{top['조합']}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sub'>{top['말']}</div>", unsafe_allow_html=True)
        st.markdown(f"<p class='small-note'>근거: {top['설명']}</p>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    with c2:
        ok = int((logs["상태"].astype(str).str.startswith("OK")).sum()) if not logs.empty else 0
        total = len(logs) if not logs.empty else 0
        st.metric("API 연결", f"{ok}/{total}")
        if not scored.empty:
            st.metric("최고 AI점수", f"{scored['AI점수'].max():.1f}")
            st.metric("분석 출전마", f"{len(scored)}두")


def main():
    cfg = load_config()

    with st.sidebar:
        st.header("⚙️ 설정")
        st.caption(f"저장 키: {mask_key(cfg.get('service_key',''))}")
        service_key = st.text_input("공공데이터 API Key", value=cfg.get("service_key", ""), type="password", help="한 번 저장하면 모바일에서 재입력하지 않아도 됩니다.")
        meet = st.selectbox("경마장", list(MEET_MAP.keys()), index=list(MEET_MAP.keys()).index(cfg.get("meet", "서울")) if cfg.get("meet", "서울") in MEET_MAP else 0)
        risk_mode = st.selectbox("분석 성향", ["균형형", "안정형", "고배당형"], index=["균형형", "안정형", "고배당형"].index(cfg.get("risk_mode", "균형형")) if cfg.get("risk_mode", "균형형") in ["균형형", "안정형", "고배당형"] else 0)
        refresh_sec = st.selectbox("자동 새로고침", [0, 30, 60, 120, 300], index=[0, 30, 60, 120, 300].index(cfg.get("refresh_sec", 0)) if cfg.get("refresh_sec", 0) in [0, 30, 60, 120, 300] else 0)
        use_demo = st.checkbox("API 안 될 때 미리보기 데이터 사용", value=False)
        if st.button("💾 설정 저장", use_container_width=True):
            cfg["service_key"] = service_key.strip()
            cfg["meet"] = meet
            cfg["risk_mode"] = risk_mode
            cfg["refresh_sec"] = refresh_sec
            save_config(cfg)
            st.success("저장 완료")
            st.rerun()

        st.divider()
        st.subheader("API URL ON/OFF")
        api_urls = cfg.get("api_urls", DEFAULT_API_URLS)
        for i, api in enumerate(api_urls):
            api["enabled"] = st.checkbox(api.get("name", f"API{i+1}"), value=api.get("enabled", True), key=f"api_on_{i}")
        cfg["api_urls"] = api_urls
        if st.button("🔌 API ON/OFF 저장", use_container_width=True):
            save_config(cfg)
            st.success("API 설정 저장 완료")

    # 자동 새로고침: Streamlit 기본만 사용. 외부 패키지 없음.
    if cfg.get("refresh_sec", 0):
        st.caption(f"자동 새로고침: {cfg['refresh_sec']}초")
        time.sleep(0.1)

    run = st.button("🚀 자동 종합 분석하기", use_container_width=True, type="primary")
    st.caption("자동 구매/자동 결제는 없습니다. 분석 결과 확인 후 본인이 직접 판단하세요.")

    if "last_scored" not in st.session_state:
        st.session_state.last_scored = pd.DataFrame()
        st.session_state.last_reco = pd.DataFrame()
        st.session_state.last_logs = pd.DataFrame()

    if run or st.session_state.last_scored.empty:
        if not cfg.get("service_key") and not service_key and not use_demo:
            logs = pd.DataFrame([{"API": "설정", "상태": "API Key 필요", "건수": 0, "시간": now_kst().strftime("%H:%M:%S")}])
            entries = pd.DataFrame()
        else:
            if service_key and service_key != cfg.get("service_key"):
                cfg["service_key"] = service_key.strip()
                cfg["meet"] = meet
                cfg["risk_mode"] = risk_mode
                cfg["refresh_sec"] = refresh_sec
                save_config(cfg)
            with st.spinner("공공데이터 API 수집 및 분석 중..."):
                dfs, logs = fetch_all(cfg)
                entries = normalize_entries(dfs)
            if entries.empty and use_demo:
                entries = demo_data()
                logs = pd.concat([logs, pd.DataFrame([{"API": "미리보기", "상태": "DEMO", "건수": len(entries), "시간": now_kst().strftime("%H:%M:%S")}])], ignore_index=True)

        scored = score_entries(entries, risk_mode=cfg.get("risk_mode", "균형형"))
        reco = make_recommendations(scored)
        if not reco.empty:
            save_history(reco, scored)
        st.session_state.last_scored = scored
        st.session_state.last_reco = reco
        st.session_state.last_logs = logs

    scored = st.session_state.last_scored
    reco = st.session_state.last_reco
    logs = st.session_state.last_logs

    render_top(scored, reco, logs)

    st.write("")
    tabs = st.tabs(["🔥 추천", "📊 출전마 점수", "🔌 API 상태", "🧾 저장 기록", "⚠️ 주의"])

    with tabs[0]:
        if reco.empty:
            st.info("추천 데이터가 없습니다.")
        else:
            st.dataframe(reco, use_container_width=True, hide_index=True)
            c1, c2 = st.columns(2)
            with c1:
                st.link_button("KRA 공식 페이지 열기", KRA_MAIN_URL, use_container_width=True)
            with c2:
                st.link_button("수동 구매 페이지로 이동", KRA_BETTING_URL, use_container_width=True)
            st.warning("구매 전 출전취소, 배당 변경, 경주시간, 본인 한도를 반드시 다시 확인하세요.")

    with tabs[1]:
        if scored.empty:
            st.info("출전마 점수 데이터가 없습니다.")
        else:
            show_cols = [c for c in ["경주", "경주시간", "마번", "말이름", "기수", "나이", "부담중량", "거리", "배당", "최근순위", "AI점수", "안정성", "배당매력", "위험도", "근거"] if c in scored.columns]
            st.dataframe(scored[show_cols], use_container_width=True, hide_index=True)
            st.download_button("CSV 다운로드", scored[show_cols].to_csv(index=False, encoding="utf-8-sig"), file_name=f"maru_kra_score_{today_str()}.csv", mime="text/csv", use_container_width=True)

    with tabs[2]:
        st.dataframe(logs, use_container_width=True, hide_index=True)
        st.caption("HTTP 500이 나오면 보통 API 엔드포인트/서비스명/인증키 인코딩/승인 상태/조회 조건 문제입니다. 해당 API만 OFF로 두고 나머지 분석은 계속 가능합니다.")

    with tabs[3]:
        hist = read_history()
        if hist.empty:
            st.info("저장 기록이 아직 없습니다.")
        else:
            st.dataframe(hist.tail(200).sort_index(ascending=False), use_container_width=True, hide_index=True)
            st.download_button("저장기록 CSV 다운로드", hist.to_csv(index=False, encoding="utf-8-sig"), file_name="maru_kra_history.csv", mime="text/csv", use_container_width=True)

    with tabs[4]:
        st.markdown("""
        ### 안전 사용 원칙
        - 이 앱은 **분석 참고용**입니다. 적중률이나 수익을 보장하지 않습니다.
        - **자동 마권 구매, 자동 결제, 몰래 구매 실행 기능은 없습니다.**
        - 배당률과 출전 정보는 실시간으로 바뀔 수 있으니 최종 구매 전 KRA 공식 화면에서 다시 확인하세요.
        - 잃어도 생활에 영향 없는 금액 안에서만 판단하세요.
        """)

    if cfg.get("refresh_sec", 0):
        # Streamlit 1.58 기준: st.rerun 사용 가능. 너무 잦은 새로고침 방지.
        time.sleep(int(cfg.get("refresh_sec", 0)))
        st.rerun()


if __name__ == "__main__":
    main()
