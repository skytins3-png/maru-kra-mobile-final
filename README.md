# MARU KRA AUTO SCHEDULER RECOMMENDER - 26 API + 18 Tickets

이 버전은 사용자 캡처 화면 기준으로 공공데이터/마사회 API URL 26개를 `api_templates.json`에 내장했습니다.

## 구매 구조
- 안정형 6장
- 고배당형 6장
- 변수형 6장
- 총 18장, 1,000원씩 총 18,000원

## API 구조
- `api_templates.json`에 26개 endpoint 저장
- endpoint에 `serviceKey`가 없으면 앱이 자동으로 `serviceKey`, `pageNo`, `numOfRows`, `_type=json`을 붙입니다.
- 실제 서비스별 세부 필수 파라미터가 다른 경우 공공데이터 문서에 맞춰 URL 뒤에 추가 파라미터를 보강해야 합니다.

## 주의
자동구매/자동결제 기능은 넣지 않았습니다. 추천번호 복사와 구매사이트 바로가기까지만 제공합니다.
