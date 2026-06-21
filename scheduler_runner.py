"""GitHub Actions/서버 cron에서 실행하는 자동 스케줄러.
- 09시대: 오늘 경주 일정 저장
- 매 실행마다: 출발 30분 전~출발 5분 후 경주 자동 분석
"""
from kra_engine import bootstrap_today_schedule, load_config, now_kst, run_due_analysis


def main():
    cfg = load_config()
    now = now_kst()
    if 9 <= now.hour <= 10:
        boot = bootstrap_today_schedule(cfg)
        print(f"[schedule] saved {boot['race_count']} races at {boot['saved_at']}")
    out = run_due_analysis(cfg)
    print(f"[analysis] checked={out['checked_at']} due={out['due_count']}")
    for r in out.get("analyzed", []):
        race = r.get("race", {})
        print(f" - {race.get('place')} {race.get('race_no')}R conf={r.get('confidence')} recs={r.get('recommend_count')}")


if __name__ == "__main__":
    main()
