# MARU KRA Mobile Final App

경마 공공데이터 API를 불러와 모바일용 대시보드에서 출전마 점수와 추천 조합을 보여주는 Streamlit 앱입니다.

## 실행 방법

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 구성

- `app.py`: 통합 앱 파일
- `requirements.txt`: 필요한 패키지
- `.maru_kra/config.json`: 앱 실행 후 자동 생성되는 설정 저장 파일
- `.maru_kra/history.csv`: 추천 기록 저장 파일

## 주의

이 앱은 분석 참고용입니다. 자동 마권 구매, 자동 결제 기능은 포함하지 않습니다.
