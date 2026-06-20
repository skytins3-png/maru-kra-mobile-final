MARU KRA CLEAN FINAL 26API STRICT CURRENT RACE

이 폴더는 GitHub 저장소를 깨끗하게 비우고 다시 올리기 위한 최종 통합본입니다.

포함 기능:
- 기존 19개 API + 추가 7개 KRA API = 총 26개 API 구조
- API URL 자동내장, API Key 재입력 없음
- API ON/OFF 관리, 전체 ON 시 26/26 강제 호출
- 현재/다음 경주번호 동기화 강화
- 현재 경주와 다른 예전 추천 숨김
- 샘플/캐시 추천은 구매 가능 추천으로 표시하지 않음
- 경주시간표/경주개요 기준 실제 경주시간 매칭
- 지나간 경주 구매 가능 표시 방지
- 더비온 등록완료 모드
- 모바일 경량 추천 화면, 10초 수동구매 화면
- 허브 저장, mobile_recommend.json, 결과/손익/빅데이터 로그
- Session State 오류 수정
- 저장시각 KeyError 수정

GitHub에 남길 정상 구조:
app.py
auto_hub_runner.py
requirements.txt
README.txt
run_app.bat
maru_kra_data/
.github/
.streamlit/

업로드 순서:
1) GitHub 저장소 안의 예전 파일을 삭제하고 Commit
2) 이 폴더의 app.py, auto_hub_runner.py, requirements.txt, README.txt, run_app.bat 업로드 후 Commit
3) maru_kra_data 폴더 업로드 후 Commit
4) .github 폴더 업로드 후 Commit
5) .streamlit 폴더 업로드 후 Commit
6) Streamlit Cloud에서 Reboot app

주의:
- ZIP 파일 자체를 올리지 말고 압축을 푼 내부 파일/폴더를 올리세요.
- __pycache__는 올리지 마세요.
- 실제 API Key는 Streamlit Secrets에 저장하세요.
- 자동구매/자동결제는 없고, 공식 더비온/마권구매 페이지에서 직접 입력/확정합니다.
