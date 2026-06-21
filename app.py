from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from kra_engine import (
    CONFIG_PATH, HUB_CSV_PATH, RESULT_CACHE_PATH, analyze_race, bootstrap_today_schedule,
    default_manual_races, latest_result, load_config, load_today_races, normalize_api_templates,
    recommendations_text, run_due_analysis, save_config, save_today_races, today_str, now_kst,
)

st.set_page_config(page_title="MARU KRA 자동 삼쌍승 추천", page_icon="🏇", layout="wide", initial_sidebar_state="collapsed")

MOBILE_CSS = """
<style>
.block-container{padding-top:1rem;padding-left:.8rem;padding-right:.8rem;max-width:1100px}
.main-title{font-size:2.05rem;font-weight:900;line-height:1.15;margin:0 0 .35rem 0}
.big-card{border:1px solid rgba(120,120,120,.25);border-radius:22px;padding:18px;margin:10px 0;background:rgba(128,128,128,.08)}
.fire{font-size:1.45rem;font-weight:900}.small{opacity:.75;font-size:.92rem}.danger{font-weight:900;color:#d14}
.combo{font-size:1.45rem;font-weight:900;letter-spacing:.5px}.metric-big{font-size:2.1rem;font-weight:900}.muted{opacity:.68}
.stButton>button{width:100%;height:3.25rem;border-radius:16px;font-weight:900;font-size:1.05rem}
[data-testid="stMetricValue"]{font-size:2rem}
@media(max-width:700px){.main-title{font-size:1.65rem}.combo{font-size:1.25rem}.metric-big{font-size:1.7rem}.big-card{padding:14px;border-radius:18px}.hide-mobile{display:none}}
</style>
"""
st.markdown(MOBILE_CSS, unsafe_allow_html=True)

cfg = load_config()

with st.sidebar:
    st.header("⚙️ 설정")
    st.caption("API Key는 화면에 저장하지 않는 게 제일 안전합니다. Streamlit/GitHub Secrets 사용을 권장합니다.")
    api_key = st.text_input("공공데이터/마사회 API Key", value=cfg.get("api_key", ""), type="password")
    buy_url = st.text_input("마권구매/공식 사이트 바로가기 URL", value=cfg.get("buy_url", "https://www.kra.co.kr/"))
    target_min_odds = st.number_input("고배당형 최소 목표 배당", min_value=1.0, max_value=500.0, value=float(cfg.get("target_min_odds", 30.0)), step=1.0)
    stake_per_combo = st.number_input("1장 구매금액", 100, 100000, int(cfg.get("stake_per_combo", 1000)), step=100)
    stable_count = st.number_input("안정형 추천 장수", 1, 20, int((cfg.get("strategy_counts") or {}).get("stable", 6)))
    high_odds_count = st.number_input("고배당형 추천 장수", 1, 20, int((cfg.get("strategy_counts") or {}).get("high_odds", 6)))
    variable_count = st.number_input("변수형 추천 장수", 1, 20, int((cfg.get("strategy_counts") or {}).get("variable", 6)))
    st.divider()
    st.subheader("API URL 30개")
    templates = normalize_api_templates(cfg.get("api_templates", []))
    txt = "\n".join(t.get("url", "") for t in templates)
    api_urls_text = st.text_area("한 줄에 URL 하나씩 붙여넣기\n{serviceKey}, {today}, {place}, {raceNo} 사용 가능", value=txt, height=220)
    if st.button("설정 저장", type="primary"):
        cfg.update({
            "api_key": api_key, "buy_url": buy_url, "target_min_odds": target_min_odds,
            "stake_per_combo": stake_per_combo,
            "strategy_counts": {"stable": stable_count, "high_odds": high_odds_count, "variable": variable_count},
            "min_recommendations": stable_count + high_odds_count + variable_count,
            "max_recommendations": stable_count + high_odds_count + variable_count,
            "api_templates": [{"name": f"API {i+1}", "url": u.strip(), "enabled": True, "kind": "general"} for i, u in enumerate(api_urls_text.splitlines()) if u.strip()]
        })
        save_config(cfg)
        st.success("저장 완료")

st.markdown('<div class="main-title">🏇 MARU KRA 자동 삼쌍승 압축 추천</div>', unsafe_allow_html=True)
st.caption("공공데이터·마사회 API를 재료로 1~12번 삼쌍승 1,320개를 점수화하고, 경주당 안정형 6장·고배당형 6장·변수형 6장 = 총 18장/18,000원 구조로 압축합니다. 자동구매/자동결제는 하지 않습니다.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🔥 다음 추천", "⏰ 일정/자동분석", "📊 전체 분석", "🧾 허브 기록", "🧩 API 상태"])

with tab1:
    col_a, col_b = st.columns([1,1])
    with col_a:
        if st.button("🔄 지금 일정 확인 + 마감 전 분석", type="primary"):
            with st.spinner("경주 시간표 기준으로 분석 대상 확인 중..."):
                out = run_due_analysis(cfg)
            if out["due_count"]:
                st.success(f"분석 완료: {out['due_count']}개 경주")
            else:
                st.warning("현재 시간 기준 30분 전~출발 5분 후 구간의 경주가 없습니다. 아래 '전체 분석'에서 수동 분석하세요.")
    with col_b:
        st.link_button("🧾 마권구매/공식 사이트 열기", cfg.get("buy_url", "https://www.kra.co.kr/"))

    result = latest_result()
    if not result:
        st.info("아직 저장된 추천이 없습니다. '전체 분석'에서 한 경주를 먼저 분석하거나, 일정 자동분석을 실행하세요.")
    else:
        race = result.get("race", {})
        st.markdown(f"""
        <div class="big-card">
          <div class="fire">🔥 {race.get('place','')} {race.get('race_no','')}경주 추천</div>
          <div class="small">출발 {race.get('start_time','미정')} · 분석 {result.get('analyzed_at','')}</div>
        </div>
        """, unsafe_allow_html=True)
        m1,m2,m3,m4 = st.columns(4)
        m1.metric("전체 조합", f"{result.get('total_combos',0):,}개")
        m2.metric("추천 압축", f"{result.get('recommend_count',0)}장")
        m3.metric("총 구매금액", f"{result.get('budget_1000',0):,}원")
        m4.metric("신뢰도", f"{result.get('confidence',0)}점")
        if result.get("status") == "구매 보류":
            st.error("현재 신뢰도가 낮아 구매 보류입니다. 무리하게 따라가지 않는 게 맞습니다.")
        recs = result.get("recommendations", [])
        if recs:
            copy_text = recommendations_text(result)
            st.text_area("복사용 추천번호", value=copy_text, height=260)
            strategy_recs = result.get("strategy_recommendations") or {}
            strategy_order = [("stable", "🛡️ 안정형"), ("high_odds", "🔥 고배당형"), ("variable", "🎲 변수형")]
            for key, label in strategy_order:
                rows = strategy_recs.get(key, [])
                st.markdown(f"### {label} {len(rows)}장")
                for i, r in enumerate(rows, 1):
                    st.markdown(f"""
                    <div class="big-card">
                        <div class="combo">{label} {i}&nbsp;&nbsp;{r['combo']}</div>
                        <div>점수 <b>{r['score']}</b> · 예상배당 <b>{r['estimated_odds']}배</b> · 위험도 <b>{r['risk']}</b></div>
                        <div class="small">{result.get('stake_per_combo',1000):,}원 적중시 단순 예상 {r['expected_return_1000']:,}원</div>
                    </div>
                    """, unsafe_allow_html=True)

with tab2:
    st.subheader("오늘 경주 시간표")
    c1,c2,c3 = st.columns(3)
    with c1:
        if st.button("🌅 오늘 일정 자동 저장"):
            with st.spinner("API에서 오늘 경주 일정 찾는 중..."):
                boot = bootstrap_today_schedule(cfg)
            st.success(f"오늘 일정 {boot['race_count']}개 저장 완료")
    with c2:
        if st.button("🧪 기본 일정 생성"):
            save_today_races(default_manual_races())
            st.success("기본 일정 저장 완료")
    with c3:
        if st.button("⏱️ 지금 마감 전 경주 분석"):
            out = run_due_analysis(cfg)
            st.success(f"확인 완료 / 대상 {out['due_count']}개")

    races = load_today_races(cfg)
    df_races = pd.DataFrame(races)
    edited = st.data_editor(df_races, use_container_width=True, num_rows="dynamic", key="races_editor")
    if st.button("수정한 일정 저장"):
        rows = edited.fillna("").to_dict(orient="records")
        save_today_races(rows)
        cfg["manual_races"] = rows
        save_config(cfg)
        st.success("일정 저장 완료")

    st.info("Streamlit 화면만으로는 폰이 앱을 닫으면 완전한 백그라운드 실행이 제한됩니다. 그래서 이 파일에는 GitHub Actions용 scheduler_runner.py와 .github/workflows/kra_scheduler.yml도 포함했습니다.")

with tab3:
    st.subheader("경주 하나 즉시 분석")
    races = load_today_races(cfg)
    labels = [f"{r.get('start_time','미정')} · {r.get('place')} {r.get('race_no')}경주 · {r.get('horse_count',12)}두" for r in races]
    idx = st.selectbox("분석할 경주", range(len(races)), format_func=lambda i: labels[i] if labels else "없음") if races else None
    if idx is not None:
        race = races[int(idx)]
        if st.button("🔥 삼쌍승 1,320개 생성 → 압축 추천", type="primary"):
            with st.spinner("API 수집·말 점수·조합 점수·위험 필터 계산 중..."):
                result = analyze_race(race, cfg)
            st.success("분석 완료")
            st.rerun()
    result = latest_result()
    if result:
        st.subheader("말별 점수")
        st.dataframe(pd.DataFrame(result.get("horse_scores", [])), use_container_width=True, hide_index=True)
        st.subheader("상위 100개 조합 / 전략별 점수 포함")
        st.dataframe(pd.DataFrame(result.get("top_all", [])), use_container_width=True, hide_index=True)

with tab4:
    st.subheader("허브 저장 기록")
    if HUB_CSV_PATH.exists():
        df = pd.read_csv(HUB_CSV_PATH)
        st.dataframe(df.tail(300).iloc[::-1], use_container_width=True, hide_index=True)
        st.download_button("CSV 다운로드", HUB_CSV_PATH.read_bytes(), file_name="kra_hub_history.csv", mime="text/csv")
    else:
        st.info("아직 허브 기록이 없습니다.")
    st.caption("Google Sheets 저장은 Secrets에 SHEET_ID, SERVICE_ACCOUNT_JSON을 넣으면 자동으로 같이 저장됩니다.")

with tab5:
    st.subheader("API 연결 상태")
    result = latest_result()
    if result.get("api_status"):
        st.dataframe(pd.DataFrame(result.get("api_status", [])), use_container_width=True, hide_index=True)
    else:
        st.info("분석을 한 번 실행하면 API별 성공/실패/행 수가 여기에 표시됩니다.")
    st.code("""사용 가능한 URL 치환값:
{serviceKey}  공공데이터/마사회 API Key
{today}       오늘 날짜 YYYYMMDD
{place}       서울/부산/제주 등
{raceNo}      경주번호
""")
