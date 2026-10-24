\# INC-001 — Azure Cost Management API 429 Too Many Requests



\## Summary

Azure 수집기(`azure\_exporter.py`)에서 비용 데이터 수집(`collect\_cost()`) 시

Azure Cost Management API가 `429 Too Many Requests`를 반환하며 비용 데이터 전송이

실패했다. 자원(리소스) 데이터 전송에는 영향이 없었다.



\## Severity

\*\*P3\*\* — 분석/추천에 필요한 비용 데이터 수집 일부 실패. 전체 파이프라인 및

자원 데이터 수집은 정상 동작.



\## Impact

\- Azure 비용 데이터(`cost\_records`)가 해당 시점에 DB에 저장되지 않음

\- Azure 자원 데이터(CPU/메모리/디스크)는 정상 전송·저장됨 (영향 없음)

\- 다른 클라우드(AWS, GCP) 수집에는 영향 없음



\## Detection

`py collectors\\azure\_exporter.py` 실행 중 터미널에 아래 트레이스백 출력으로 확인.



```text

\[OK] 자원 데이터 저장 성공: vm-finops-azure-test

Traceback (most recent call last):

&#x20; ...

&#x20; File "azure\_exporter.py", line 374, in run\_send

&#x20;   cost\_rows = collect\_cost(cost\_client, config\["subscription\_id"], config\["resource\_group"])

&#x20; File "azure\_exporter.py", line 290, in collect\_cost

&#x20;   result = client.query.usage(scope=scope, parameters=query)

&#x20; ...

azure.core.exceptions.HttpResponseError: (429) Too many requests. Please retry.

Code: 429

Message: Too many requests. Please retry.

```



\## Timeline (2026-07-30, KST/UTC+9 기준, 원본 timestamp는 UTC)

| 시각(KST) | 시각(UTC, 원본) | 내용 |

|-----------|----------------|------|

| 18:06 | 09:06 | `--dry-run`으로 `collect\_cost()` 1차 호출 (성공, 값 확인용) |

| 18:17 | 09:17 | `py collectors\\azure\_exporter.py` 실행 → 자원 데이터 전송 성공, 비용 수집에서 429 발생 |

| 18:28 | 09:28 | 재시도 → 동일하게 429 발생 |

| 18:52 | 09:52 | 약 25분 대기 후 재시도 → 자원 + 비용 데이터 모두 전송 성공 |



\## Symptoms

\- 자원 데이터 전송은 매번 정상 (`\[OK] 자원 데이터 저장 성공`)

\- 비용 데이터 수집 단계(`client.query.usage()`)에서만 `HttpResponseError: (429)` 발생

\- 짧은 간격(수 분 이내) 재시도 시에는 계속 동일 에러 재현됨



\## Root Cause

Azure Cost Management Query API에는 \*\*스코프(구독)당 분당 4회\*\*라는

공식적인 내부 호출 제한이 걸려 있음(Microsoft 공식 Q\&A 확인).

당일 `--dry-run` 1회 + 실제 실행(`run\_send`) 2회, 총 3\~4회 이상의

`collect\_cost()` 호출이 짧은 시간 안에 발생하여 이 제한을 초과했다.



\- Azure Plan(후원/파트너 경유 구독)이라서 생긴 문제는 \*\*아님\*\* — 일반 구독에도

&#x20; 동일하게 적용되는 API 자체의 하드 리밋으로 확인됨

\- 참고: \[Azure Cost Management API 429 관련 Microsoft Q\&A](https://learn.microsoft.com/en-us/answers/questions/1603465/429-too-many-requests-when-using-azure-cost-manage)



\## Recovery

약 25분 대기 후 재실행하여 정상 처리됨. 별도의 코드 수정 없이

시간 간격을 둔 재시도만으로 복구됨.



```text

\[OK] 자원 데이터 저장 성공: vm-finops-azure-test

\[OK] 비용 데이터 저장 성공: 2026-07-30 / Storage

\[OK] 비용 데이터 저장 성공: 2026-07-30 / Virtual Network

\[OK] 비용 데이터 저장 성공: 2026-07-30 / Log Analytics

\[OK] 비용 데이터 저장 성공: 2026-07-30 / Virtual Machines

```



\## Prevention

\- \*\*단기(현재)\*\*: 비용 수집 관련 테스트/실행 시 최소 1\~2분 이상 간격을 두고

&#x20; 수동으로 재시도. 짧은 간격 연속 재시도는 지양.

\- \*\*중기(차주 반영 검토)\*\*:

&#x20; 1. `collect\_cost()`에 429 응답 시 `Retry-After` 헤더 값만큼 자동 대기 후

&#x20;    재시도하는 백오프 로직 추가

&#x20; 2. 자원 데이터와 비용 데이터의 수집 주기를 분리 (비용은 DAILY 단위 집계이므로

&#x20;    자원 데이터만큼 자주 조회할 필요 없음) — 차주 계획에 수집 주기 분리

&#x20;    항목이 있는지 확인 후 반영 여부 결정

\- 이 결정 사항은 별도로 `decisions/000X-collect-interval-separation.md`로

&#x20; 기록 검토



\## Evidence

\- 캡처: `evidence/week5-azure-cost-429-fail-1.png` (1차 429 발생, 재시도 전)

!\[week5-azure-cost-429-fail-1](../evidence/week5-azure-cost-429-fail-1.png)

\- 캡처: `evidence/week5-azure-cost-429-fail-2.png` (2차 재시도 후에도 재현)

!\[week5-azure-cost-429-fail-2](../evidence/week5-azure-cost-429-fail-2.png)

\- 캡처: `evidence/week5-azure-send-ok-1.png` (최종 재시도 성공, 자원+비용 앞부분)

!\[week5-azure-send-ok-1](../evidence/week5-azure-send-ok-1.png)

\- 캡처: `evidence/week5-azure-send-ok-2.png` (최종 재시도 성공, 비용 전 서비스 완료)

!\[week5-azure-send-ok-2](../evidence/week5-azure-send-ok-2.png)

