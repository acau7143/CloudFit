# 0003. 팀 공통 데이터 스키마 필드 통일

## Context
AWS(A)/Azure(B)/GCP(C)가 각자 수집기를 만들면서 `to_common_record()`,
`to_common_cost_record()` 필드명과 값 형식이 서로 달랐음
(예: `cloud` 값 대소문자, `instance_id` vs `resource_id`,
`cpu_avg` vs `cpu_percent`, 계산 방식 차이 등).
3주차 팀 미팅에서 세 명의 `--dry-run` 결과를 나란히 대조하여 통일함.

## Decision
GCP(C) 코드의 필드 구성을 기준으로 통일한다.

- `cloud`: `"AWS"` / `"Azure"` / `"GCP"` (약어는 대문자, 고유명사는 첫 글자만 대문자)
- 식별자: `instance_id`
- 자원 지표: `cpu_avg`, `memory_avg`, `disk_avg` — **구간 전체 평균값** (순간값 아님)
- 비용 지표: `cloud`, `date`, `cost_usd`, `currency`, `service`, `granularity`

## Why
- 서버(FastAPI) 쪽에서 클라우드별로 다른 변환 로직을 짤 필요 없이,
  수집기 단에서 미리 형식을 맞추는 게 구조가 단순함
- "평균" 방식이 순간 스파이크에 덜 흔들려서 저활용/과부하 판단 기준으로 더 안정적
- 이미 GCP/AWS 코드가 이 방식(전체 평균)과 유사하게 짜여 있어 변경 비용이 가장 적음

## 대안과의 비교
| 대안 | 문제점 |
|------|--------|
| 각자 스타일 유지 + 서버에서 변환 | 클라우드 3개 = 변환 로직 3개, 스키마 바뀔 때마다 서버 코드도 같이 고쳐야 함 |
| 최근 값(순간값) 방식으로 통일 | 스파이크에 취약해 저활용 오판 가능성 높음 |
| Azure 기준으로 통일 | Azure가 GCP/AWS보다 필드/로직이 더 복잡해서 다른 두 클라우드 코드도 크게 뜯어고쳐야 함 |

## Result
- Azure 코드(`azure_exporter.py`)를 GCP 기준으로 리팩터링 완료
  (필드명, `cloud` 값 표기, 평균 계산 로직 모두 수정)
- AWS 코드는 필드명은 이미 일치, 계산 방식(최근 5분 구간 값 1개)만 추후 수정 필요 — **미해결**