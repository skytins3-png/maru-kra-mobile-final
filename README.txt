MARU KRA CLEAN HOTFIX FAST LOAD

이번 버전은 Streamlit Cloud 첫 화면이 흰색 스피너에서 오래 멈추는 문제를 막기 위한 핫픽스입니다.

핵심 변경:
- HOTFIX_LOADING_FAST 적용
- 첫 화면 API 자동호출 OFF
- 기본 API 수집 모드: 허브만 분석
- 실시간 데이터는 버튼 클릭 시만 수집
- 자동 새로고침 기본 OFF
- 외부 API timeout 단축
- 기존 26개 API, 현재 경주 동기화, 더비온 등록완료 모드, 모바일 추천 구조 유지

업로드:
1) GitHub 새 저장소 루트에 app.py, auto_hub_runner.py, requirements.txt, README.txt, run_app.bat 업로드
2) maru_kra_data, .github, .streamlit 폴더 업로드
3) Streamlit Cloud에서 Reboot app
4) 브라우저에서 ?v=fastload 를 붙여 새로 열기
