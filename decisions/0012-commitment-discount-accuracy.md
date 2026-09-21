# 0012. 클라우드별 약정 할인율 산정 방식

## Context

Week10에서 `ml/recommend.py`에 클라우드별 약정 할인(AWS/Azure Reserved Instance,
GCP Committed Use Discount) 전환 추천 기능(`commitment_recommendation`,
`estimated_discount_pct`)을 추가했다.

초기 `COMMITMENT_INFO` 값은 "1년 No Upfront 공식 문서상 30~40% 범위의 중간값"
같은 업계 통용 근사치였다. 문제는 `/recommendations` API가 이 근사치를
`"estimated_discount_pct": 35.0`처럼 그대로 응답에 내보낸다는 점이다. `float`
단일값이라 마치 실측 정밀값처럼 보이는데, 실제로는 근사치라는 게 API 응답만
봐서는 전혀 드러나지 않는다.

## Decision

근사치를 유지하되 문서에만 한계를 명시하는 방식 대신, **각 클라우드의 공식
가격 조회 API로 이 프로젝트가 실제 사용 중인 인스턴스 종류·리전 기준 실측
할인율을 1회 조회해서 `COMMITMENT_INFO`에 반영**한다.

상시 도는 파이프라인이 아니라 클라우드별 조사용 스크립트로 만들고, 각 클라우드
담당자가 자기 인증 정보로 직접 실행한다.

| 클라우드 | API | 인증 | 상태 |
|---|---|---|---|
| AWS | Price List API (`boto3.client('pricing')`, us-east-1 고정) | IAM 자격증명 필요 | 완료 (39.23%) |
| Azure | Retail Prices API (prices.azure.com) | 불필요 (완전 공개) | 완료 (44.4%) |
| GCP | Cloud Billing Catalog API | 서비스 계정 필요 | 완료 (37.0%) |

## Why

- API 응답 구조(단일 `float` 필드)가 "근사치"와 "실측값"을 구분하지 못해서,
  근사치를 그대로 두면 API 소비자(대시보드, 발표 심사위원)가 정밀 실측값으로
  오해할 수 있음
- 발표/심사 중 "이 수치는 어떻게 나온 거냐"는 질문에 "실제 가격 API로
  조회했다"고 답할 수 있어야 신뢰도가 생김
- 완전 자동화(추천 생성 시마다 실시간 API 호출)는 클라우드당 반나절~하루
  소요로 Week10 잔여 일정(Day4~5 대시보드·통합테스트·README)에 부담이 큼

## 대안과의 비교

| 대안 | 소요 시간 | 비교 |
|---|---|---|
| 근사치 유지 + 문서에 한계만 명시 | 0 | 가장 빠르지만, API가 부정확한 값을 정밀값처럼 계속 노출하는 문제는 그대로 남음 |
| **1회 API 조회 후 하드코딩 교체 (채택)** | 클라우드당 1~2시간 | 정확도 개선 대비 시간 부담이 적음. 인스턴스 타입/리전이 바뀌면 재조회 필요 |
| 실시간 API 연동 (추천 생성마다 호출) | 반나절~하루 | 가장 정확하지만 SKU 매칭·캐싱·에러 처리까지 갖춰야 해서 이번 주 일정엔 부적합. 향후 개선 방향으로 보류 |

## Result — Azure (B, 은창)

### 조사 대상

- 실제 운영 VM 확인: `az vm show`로 `Standard_B2ats_v2` / `koreacentral` /
  Linux 확인 (`azure_exporter.py`가 cron으로 수집 중인 VM과 동일)

### 조회 방법

Azure Retail Prices API를 PowerShell(`Invoke-RestMethod`)에서 직접 호출:

```
armSkuName eq 'Standard_B2ats_v2' and armRegionName eq 'koreacentral' and type eq 'Reservation'
armSkuName eq 'Standard_B2ats_v2' and armRegionName eq 'koreacentral' and type eq 'Consumption'
```

### 계산

| 항목 | 값 |
|---|---|
| 온디맨드 (Linux) | $0.0117/시간 → 연 환산 약 $102.5 |
| 1년 예약 총액 | $57 |
| 3년 예약 총액 | $117 (연 환산 $39) |
| **1년 실측 할인율** | **44.4%** |
| 3년 실측 할인율 (참고) | 61.9% |

**주의 — API 표기 오류**: Reservation 타입 항목의 `unitOfMeasure`는 "1 Hour"로
표시되지만, `retailPrice`는 실제로 시간당 가격이 아니라 **약정 기간 전체
총액**이다. 이 값을 시간당 가격으로 착각하면 계산이 완전히 틀어지므로,
다음에 이 API를 다시 쓸 때 주의할 것.

### 부수적으로 확인된 사실 — B-시리즈 RI 지원 여부

이전에 "B-시리즈(버스터블)는 전통 Reserved VM Instance를 지원하지 않을 것"
이라는 추정이 있었으나, `type eq 'Reservation'` 쿼리에서 1년/3년 항목이 정상
조회됨을 확인 — 최소한 `B2ats_v2` 세대는 **RI를 지원**한다. 따라서
`commitment_recommendation` 라벨은 `'reserved_instance'`를 그대로 사용.

### `COMMITMENT_INFO` 반영

```python
'Azure': {'label': 'reserved_instance', 'discount_pct': 44.4},
```

`ml/recommend.py`에 반영 완료, `python3 ml/recommend.py --dry-run | grep Azure`로
검증 완료. `feature/aws-collector` 브랜치에 커밋·푸시됨.

### uptime_ratio_7d 판정 근거 확인

`judge_commitment()`가 쓰는 `uptime_ratio_7d`(가동 시간 비율 = 최근 7일 실제
레코드 수 / 기대 레코드 수 2016)의 전제 — "레코드 존재 = VM 가동 중" — 가
Azure 트랙에서도 유효한지 확인함. `azure_exporter.py`는 Azure VM **자체
내부**에서 5분 주기 crontab으로 실행되므로(6주차에 구축), VM이 꺼지면 cron
자체가 돌 수 없어 레코드가 자연스럽게 비게 된다. 즉 로컬/원격에서 API를
호출하는 방식이 아니라, "레코드 존재 = 가동 중" 전제가 안전하게 성립함.

### 비용 예측 (Day3)

`ml/cost_forecast.py --cloud Azure` 실행, `cost_forecast` 테이블에 7일치
(2026-09-19 ~ 2026-09-25) 예측 저장 완료.

### Grafana 대시보드 (Day4)

멀티클라우드 대시보드에 Azure 비용 예측 패널 추가: 실제 비용(실선) + 예측
비용(점선, Line style override) + 예측 상·하한 음영(Fill below to override).

## 남은 것

- AWS(A), GCP(C) 파트는 각 담당자가 채우거나, `ml/recommend.py` 주석에 이미
  반영된 실측치(AWS 39.23%, GCP 37.0%)를 그대로 가져와 위 표에 채워 넣으면
  Context/Result 취합 완료
- 3개 클라우드 Result가 모두 확정되면 팀 전체 리뷰 후 `main`/`dev`로 merge