# INC-002 — ML 이상탐지 오탐 (synthetic 데이터 오염)

## Summary
`ml/train.py`가 `resource_metrics`를 `source`(real/synthetic) 구분 없이 통째로 학습에 사용하면서, 학습 데이터의 87%를 차지하는 synthetic 데이터가 실제 서버의 정상 CPU 범위를 왜곡시켰다. 그 결과 Isolation Forest 모델이 AWS/Azure의 정상적인 real 데이터를 전부 "이상"으로, GCP의 real 데이터는 전부 "정상"으로 판정하는 극단적인 오류가 발생했다.

## Severity
**P3** — 분석/추천 결과 오류. 수집 파이프라인 자체는 정상 동작하며 데이터 유실은 없음. 다만 `/anomalies` API와 Grafana 이상탐지 패널의 결과값을 신뢰할 수 없는 상태.

## Impact
- `/anomalies?cloud=AWS`, `/anomalies?cloud=Azure` — 조회되는 결과가 사실상 전체 데이터(100%)라 "이상탐지"로서 의미 없음
- `/anomalies?cloud=GCP` — 이상 판정이 0%로 나오지만, 이것도 모델이 제대로 판단해서가 아니라 real·synthetic 평균값이 우연히 가까워서 생긴 결과라 신뢰 불가
- Grafana "이상 탐지 결과" 패널에서 AWS/Azure 실제 CPU 라인 위에 이상 표시가 항상 겹쳐서 찍힘 (시각적으로도 확인됨)

## Detection
8/20 Grafana에서 "이상 탐지 결과" 패널(B가 신규 추가)을 확인하던 중, AWS·Azure는 CPU 값과 무관하게 매 시점 빨간 이상 표시가 찍히고, CPU가 가장 높은 GCP는 이상 표시가 전혀 없는 역전 현상을 시각적으로 발견.

## Timeline (2026-08-20 기준)
1. Grafana 이상탐지 패널에서 AWS/Azure 100%·GCP 0% 이상 판정 패턴 육안 발견
2. `anomaly_results` ↔ `resource_metrics` JOIN으로 실시간 탐지 저장 단계의 synthetic 오염 여부 확인 → **오염 없음** (3,908건 전부 `source=real`), 문제가 실시간 탐지가 아니라 학습 단계에 있다는 쪽으로 좁혀짐
3. `resource_metrics`를 `cloud`, `source`별로 그룹핑해 평균 CPU 비교 → real과 synthetic 평균 격차 확인, 근본 원인 확정

## Symptoms
- Grafana 패널: AWS(`cpu_avg` ~3%), Azure(`cpu_avg` ~1%) 라인 위에 항상 빨간 이상 점이 겹쳐 찍힘. GCP(`cpu_avg` ~20%)는 이상 점이 하나도 없음

  ![Grafana 이상탐지 패널 - AWS/Azure 100% 오탐, GCP 0%](../evidence/week07-anomaly-100pct-bug-detected.png)

- SQL 재현:
  ```sql
  SELECT cloud, anomaly, COUNT(*)
  FROM anomaly_results
  GROUP BY cloud, anomaly
  ORDER BY cloud, anomaly;
  -- AWS: anomaly=true 92/92 (100%)
  -- Azure: anomaly=true 77/77 (100%)
  -- GCP: anomaly=false 92/92 (0%)
  ```

## Root Cause
`ml/train.py`의 학습 데이터 조회 쿼리가 `source` 컬럼으로 필터링하지 않아, real 데이터(약 13%)와 synthetic 데이터(약 87%)가 섞인 채로 모델이 학습됨. 클라우드별 real/synthetic 평균 CPU를 비교하면 원인이 명확히 드러남.

```sql
SELECT cloud, source,
       ROUND(AVG(cpu_avg)::numeric,2) avg_cpu,
       ROUND(MIN(cpu_avg)::numeric,2) min_cpu,
       ROUND(MAX(cpu_avg)::numeric,2) max_cpu,
       COUNT(*)
FROM resource_metrics
GROUP BY cloud, source
ORDER BY cloud, source;
```

| cloud | source | avg_cpu | 격차(synthetic/real) |
|-------|--------|---------|----------------------|
| AWS | real | 2.88% | synthetic 21.98% — 약 7.6배 |
| Azure | real | 0.85% | synthetic 59.40% — **약 70배** |
| GCP | real | 21.91% | synthetic 43.80% — 약 2배 |

![resource_metrics cloud×source 평균 CPU 비교 쿼리 결과](../evidence/week07-root-cause-query-result.png)

synthetic이 학습 데이터를 압도(87%)하다 보니, 모델은 "정상 범위"를 synthetic 분포 기준으로 학습했다. Azure는 그 왜곡이 가장 심해서(70배 격차) real 데이터가 극단적 이상치로 보였고, GCP는 real·synthetic 격차가 상대적으로 작아 우연히 정상 범위 안에 들어간 것뿐이다. **GCP 결과가 "맞아 보이는 것"도 모델이 정확해서가 아니라 우연이므로 셋 다 신뢰할 수 없는 상태.**

## Recovery
1. `ml/train.py`의 학습 데이터 조회 쿼리에 `AND source = 'real'` 추가 (synthetic 제외)
2. real 데이터만으로 재학습 → `ml/model.pkl` 갱신
3. `ml/anomaly_detector.py` 재실행 → `anomaly_results` 재계산
4. 재검증:
   ```sql
   SELECT cloud, anomaly, COUNT(*) FROM anomaly_results GROUP BY cloud, anomaly ORDER BY cloud, anomaly;
   ```
   AWS/Azure의 이상 비율이 100%에서 정상 범위(대략 5% 근처, contamination 설정값)로 내려오는지 확인
5. (8주차 계획에 포함) synthetic의 `pattern` 정답 라벨로 재학습된 모델의 탐지 정확도를 별도 검증 (`ml/validate_with_synthetic.py`)

## Prevention
- synthetic 데이터처럼 **다른 팀원의 코드가 참조하는 공통 테이블에 새 데이터를 추가할 때**, 그 데이터를 쓰는 다른 스크립트(`train.py`, `anomaly_detector.py` 등)에 미치는 영향을 사전에 팀 채팅으로 공유한다 (CLAUDE.md 3장 "공통 데이터 형식은 항상 일치해야 한다" 원칙과 직결)
- 학습용 데이터와 실서비스 데이터를 같은 테이블에 둘 때는 `source` 같은 구분 컬럼을 만드는 것만으로는 부족하고, **그 컬럼을 실제로 필터링하는 코드까지 함께 확인**해야 한다
- ML 모델을 재학습할 때마다 클라우드별 이상 판정 비율을 확인하는 걸 체크리스트에 포함 (100%/0% 같은 극단값이 나오면 즉시 의심)

## Evidence
- `evidence/week07-anomaly-100pct-bug-detected.png` — Grafana 이상탐지 패널, AWS/Azure 매 시점 이상 표시·GCP 이상 표시 없음 (Symptoms 섹션에 첨부)
- `evidence/week07-root-cause-query-result.png` — `resource_metrics` cloud×source 평균 CPU 비교 쿼리 결과 (Root Cause 섹션에 첨부)