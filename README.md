# CloudFit — 멀티클라우드 FinOps 모니터링 프로젝트

> **진행 중 문서입니다.** 최종 완성본은 11주차(9월 초)에 정리 예정이며, 이 버전은 4주차(2026-07-25) 기준 진행 상황을 담고 있습니다.

AWS / Azure / GCP 세 클라우드에 흩어진 자원 사용률과 비용 데이터를 한 곳에 모아서, 나중에 저활용 자원 탐지·비용 최적화 추천·ML 기반 이상탐지까지 확장하는 것을 목표로 하는 팀 프로젝트입니다. 한이음 드림업 공모전 제출, 캡스톤 발표, 논문게재 신청을 목표로 진행 중입니다.

- 기간: 2026.06.23 ~ 2026.10.08 (15주)
- 팀: A(AWS 담당) · B(Azure 담당) · C(GCP 담당)

---

## 지금 뭐가 되나 (10주차 기준)

수집 파이프라인 위에 이상탐지, 추천, 예측까지 얹은 상태입니다. 인프라는 4주차 이후 개인 노트북+ngrok에서 EC2 상시 운영으로 이전했습니다.

| 항목 | 상태 |
|------|------|
| 자원/비용 수집 (AWS/Azure/GCP) | 완료 (5분/1일 주기 cron 자동화) |
| 공통 스키마 정렬 (decisions/0001, 0002) | 완료 |
| 중앙 서버 (FastAPI + PostgreSQL) | EC2 인스턴스에서 Docker Compose로 상시 운영 |
| ML 이상탐지 (Isolation Forest, 클라우드별 모델) | 완료 |
| 비용 최적화 추천 (downsize/keep) | 완료 |
| Grafana 대시보드 | 운영 중 |
| 미사용 리소스 탐지 (AWS 완료 / Azure GCP 각자 확인 필요) | AWS - collectors/aws_unused_detector.py, unused_resources 테이블 |
| 예산 초과 Slack 알림 (AWS 완료 / Azure GCP 각자 확인 필요) | AWS - server/budget_alert.py |
| 예약 인스턴스(RI) 전환 추천 (AWS 완료 / Azure GCP 각자 확인 필요) | AWS - ml/recommend.py에 commitment_recommendation 컬럼 추가 |
| 비용 예측 (Prophet, AWS 완료 / Azure GCP 각자 확인 필요) | AWS - ml/cost_forecast.py, cost_forecast 테이블 |

> Azure(B), GCP(C) 담당 항목의 최신 상태는 각자 업데이트 부탁드립니다 (10주차 기준 AWS만 확인 완료).

---

## 아키텍처

```
[AWS EC2]  --\
[Azure VM] ---+--> collector (Python, cron) --> to_common_record() --> HTTP POST --\
[GCP VM]   --/                                                                      v
                                                              FastAPI 서버 (EC2, Docker Compose)
                                                                       |
                                                                       v
                                                     PostgreSQL (resource_metrics, cost_records,
                                                        anomaly_results, recommendations,
                                                        unused_resources, cost_forecast)
                                                                       |
                                        +------------------------------+------------------------------+
                                        v                              v                              v
                                  Grafana 대시보드              ml/ 배치 스크립트              server/notifier.py
                                  (실측값 + 이상탐지            (anomaly_detector,                    |
                                   오버레이 패널)                recommend, cost_forecast)             v
                                                                       |                          Slack 알림
                                                                       v                    (미사용 리소스 발견,
                                                                 결과를 다시 DB에 저장             예산 초과)
```

각 클라우드의 수집기가 5분 간격 자원 지표와 하루 1회 비용 지표를 조회해 공통 스키마로 변환한 뒤 중앙 서버 API로 전송합니다. 서버는 EC2 인스턴스 위 Docker Compose로 PostgreSQL·Grafana와 함께 상시 운영됩니다.

ml/ 아래 배치 스크립트들이 주기적으로(또는 수동 실행으로) DB를 읽어 이상탐지·추천·예측 결과를 다시 DB에 써넣고, unused_resources나 예산 초과 같은 즉시성 있는 이벤트는 server/notifier.py를 통해 Slack으로 알림이 갑니다.

---

## 폴더 구조

```
CloudFit/
├── collectors/           # 클라우드별 수집기 (aws_exporter.py, azure_exporter.py, gcp_exporter.py)
├── server/                # FastAPI 중앙 서버 (main.py, database.py, Dockerfile)
├── db/schema.sql           # PostgreSQL 테이블 정의 (resource_metrics, cost_records)
├── tests/                  # 수집기별 단위 테스트
├── diary/                  # 팀원별 작업 일지 (YYYY-MM-DD-weekNN-{이름}.md)
├── runbook/                 # 설치·실행·복구 절차 문서
├── decisions/                # 기술/설계 결정 기록
├── incidents/                 # 장애 기록 (발생 시 작성)
├── evidence/                   # 검증 캡처 이미지
└── docker-compose.yml          # DB + 서버 통합 실행 정의
```

---

## 기술 스택

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.11+ |
| 백엔드 | FastAPI, asyncpg, SQLAlchemy(async) |
| DB | PostgreSQL 15 (Docker) |
| AWS 수집 | boto3 (CloudWatch, Cost Explorer) |
| Azure 수집 | azure-mgmt-monitor, azure-monitor-query, azure-mgmt-costmanagement |
| GCP 수집 | google-cloud-monitoring, google-api-python-client, BigQuery(billing export) |
| 컨테이너 | Docker, Docker Compose |
| 테스트 | pytest / unittest |
| (예정) ML | scikit-learn (Isolation Forest) — 7주차부터 |
| (예정) 시각화 | Grafana — 8주차부터 |

---

## 공통 데이터 스키마

세 명의 수집기가 각자 다른 필드명/계산 방식을 쓰다가 3주차 팀 미팅에서 GCP 코드를 기준으로 통일했습니다 (`decisions/0001-common-schema.md`).

**resource_metrics** (5분 간격, 구간 전체 평균값)

| 컬럼 | 설명 |
|------|------|
| `cloud` | `AWS` / `Azure` / `GCP` |
| `instance_id` | 인스턴스 식별자 |
| `timestamp` | 수집 시각 (TIMESTAMPTZ) |
| `cpu_avg`, `memory_avg`, `disk_avg` | 구간 평균 사용률(%) |
| `instance_type`, `vcpu`, `ram_gb` | 인스턴스 사양 |

**cost_records** (하루 1회, 서비스별 여러 행 — `decisions/0002-cost-schema.md`)

| 컬럼 | 설명 |
|------|------|
| `cloud`, `date`, `service` | 클라우드 / 날짜 / 서비스명 |
| `cost_usd`, `currency` | 비용(USD 환산), 통화 |
| `granularity` | 현재 `DAILY` 고정 |

자원 데이터와 비용 데이터는 수집 주기(5분 vs 하루)와 단위(% vs USD)가 달라 별도 테이블로 분리했습니다.

---

## 시작하기

**1. 중앙 서버 + DB 실행**
```bash
docker compose up --build
curl http://localhost:8000/health   # {"status":"ok"} 확인
```

**2. 수집기 실행 (각자 담당 클라우드에서)**
```bash
# 포맷만 확인 (서버 전송 없음)
python3 collectors/gcp_exporter.py --dry-run

# 실제 서버 전송
python3 collectors/gcp_exporter.py
```

**3. 저장 확인**
```bash
curl "http://localhost:8000/resources?cloud=GCP" | python3 -m json.tool
curl "http://localhost:8000/costs?cloud=GCP" | python3 -m json.tool
```

원격 VM(AWS EC2 / Azure VM / GCP VM)에서 로컬 서버로 접속해야 하는 경우, 서버 주소가 `localhost`이면 원격에서는 접속이 안 됩니다. 현재는 ngrok 임시 터널을 통해 연결하고 있으며, 무료 ngrok을 쓸 경우 요청 헤더에 `ngrok-skip-browser-warning: true`를 추가해야 합니다.

---

## 알려진 이슈 / TODO

- **서버가 임시 상태**: A의 로컬 노트북 + ngrok 터널로만 접속 가능. 클라우드 인스턴스로 정식 배포 필요 (팀 논의 중)
- **비용 데이터 중복 저장 가능성**: `collect_cost()`가 매번 최근 7일치를 다시 조회해서 전송하는 구조라, 반복 실행 시 겹치는 날짜의 비용 레코드가 중복 저장됨. `(cloud, date, service)` 유니크 제약이나 upsert 로직 필요
- **인증 없음**: 현재 API에 별도 인증이 없어 URL만 알면 누구나 데이터를 넣을 수 있음. 정식 배포 전 API 키 등 추가 필요
- **`SERVER_URL` 하드코딩**: `.env` 기반으로 분리하기로 계획했으나 아직 미완료
- **Azure/AWS 실제 서버 연결 미검증**: GCP는 ngrok으로 실제 DB 저장까지 확인했지만, Azure는 서버 미기동 상태에서의 예외 처리까지만 확인, AWS는 로컬 자체 테스트만 진행함
- **decisions/0001 갱신 필요**: AWS가 7/24에 계산 방식을 구간 평균으로 이미 수정했는데, 문서에는 아직 "미해결"로 남아있음

---

## 앞으로 계획 (요약)

| 주차 | 목표 |
|------|------|
| 5주차 | 3개 수집기 → 서버 통합 완료, 합성 데이터 생성기 개발 |
| 6주차 | 저활용/비용 비효율 탐지 로직, 리사이징 추천 |
| 7주차 | Isolation Forest 기반 이상탐지 모델 |
| 8주차 | Grafana 대시보드 |
| 9~10주차 | 전체 파이프라인 통합 테스트, 실데이터 검증 |
| 11주차 | GitHub 정리, README/Runbook 최종화 |
| 12주차~ | 보고서, 논문 초안, 발표 준비, 최종 제출 |

전체 일정은 `project-plan.md`에 자세히 정리되어 있습니다.

---

## 문서 안내

- `diary/` — 팀원별 날짜별 작업 일지
- `runbook/` — 설치·실행·복구 절차 (재현 가능한 최신 절차 기준)
- `decisions/` — 기술 선택/설계 결정 근거
- `incidents/` — 장애 발생 시 재현 절차 포함 기록
- `evidence/` — 검증 캡처 이미지