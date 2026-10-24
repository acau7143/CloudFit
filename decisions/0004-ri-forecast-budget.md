# 0004. AWS 예약 인스턴스 추천 / 비용 예측 / 예산 알림 기준

## Context
FinOps Framework의 Optimize(약정 할인), Inform(예측), Operate(거버넌스) 영역이 비어 있었음.

## Decision
### 예약 인스턴스(RI) 추천
- 최근 7일 가동 시간 비율 90% 이상이면 `reserved_instance` 추천
- 가동 시간 비율은 리소스 수집 주기(5분 cron) 기준 기대 샘플 수(2016개) 대비
  실제 수집된 샘플 수 비율로 계산 (AWS CloudWatch 가동 로그를 별도 조회하지 않음)
- 할인율은 35%(AWS RI 1년 No Upfront 기준 대략치 30~40%의 중간값)로 잠정 적용 —
  **정확한 수치는 AWS 공식 문서로 재확인 필요, 현재는 하드코딩 상태**

### 비용 예측
- Prophet으로 `cost_records` 일별 합산 데이터 학습 → 향후 7일 예측
- 데이터 37일치 확보(7일 최소 기준 충족)

### 예산 알림
- 월 예산 $50(AWS/Azure/GCP 공통)로 잠정 설정 — **팀 확정값 아님, 논의 필요**
- `cost_records`를 매번 실시간 집계, 별도 저장 테이블 없음

## Why
- RI 판정을 기존 downsize 판단(`judge()`)과 별개 컬럼으로 분리해서, 저활용이면서
  동시에 상시 가동인 인스턴스도 두 추천이 동시에 나올 수 있게 함 (상호 배타적이지 않음)
- 예산 $50은 Week9 계획서 스켈레톤의 예시값을 그대로 사용 — 실제 클라우드 사용량 대비
  적정한지는 검증 안 됨

## Result
- `ml/recommend.py`에 `commitment_recommendation`, `estimated_discount_pct` 컬럼 추가,
  AWS 인스턴스에 `reserved_instance` 추천 확인
- `ml/cost_forecast.py` 작성, AWS 7일 예측 `cost_forecast` 테이블 저장 확인
- `server/budget_alert.py` 작성, 예산 초과 시 경고 + Slack 알림 호출 경로(Fail/Recover) 둘 다 검증 완료
