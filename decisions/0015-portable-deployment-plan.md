# 0015. 다른 클라우드 계정에서도 실행되는 이식 가능한 배포로 전환 (작업 계획서)

> 상태: **계획 (코드 미수정)** · 작성 기준: `main` (PR #4~#6 병합 직후, 4fa1747)
> 이 문서는 계획서이며, 각 단계를 진행하면서 맨 아래 "Result" 체크리스트를 갱신한다.

## Context

현재 CloudFit은 팀의 AWS·Azure·GCP 계정과 VM에서만 동작한다. 서버·DB·ML·알림은
계정과 무관하게 `docker compose up`으로 올라가지만, **수집기 코드와 설치 절차**가
우리 환경의 식별자에 묶여 있고, 운영 설정 일부(cron 등)는 저장소에 기록조차 없다.

목표: 새로운 AWS / Azure / GCP 계정(또는 다른 사람의 계정)에서 **`.env`를 채우고
설치 스크립트를 실행하면** 수집 → 서버 → 대시보드까지 동작하게 한다.

### 범위

| 구분 | 내용 |
|---|---|
| 포함 | 하드코딩 제거, 환경변수/`.env.example` 정리, 설치 자동화, 최소 권한 문서화, 서버 기본 보안, 새 계정 검증 |
| 제외 (후속 후보) | 한 클라우드에 VM 여러 대 자동 발견, Terraform 등 IaC, 멀티 테넌트(여러 조직 동시 수용), 이미 수집된 과거 데이터 이전 |

### 대상 결정 (2026-10-24): **팀 내부 재현 우선**

이 계획의 대상은 "팀원이 새 계정/VM에서 같은 환경을 다시 만들 수 있는 것"이다. 다른 사람(외부 사용자)의
계정에 배포해 운영하는 것은 **확장 계획**으로 문서에만 남기고 이번 범위에서 제외한다.

| 구분 | 팀 내부 재현 (채택) | 외부 배포 (확장 계획) |
|---|---|---|
| 설치하는 사람 | 팀원(A/B/C) | 처음 보는 사용자 |
| 목표 | 새 환경에서도 동작함을 검증·시연 | 실제 서비스로 제공 |
| 보안 | 팀이 아는 주소/계정. 최소 정리(DB 포트 등) | API 인증, 데이터 분리, 읽기 전용 최소 권한 필수 |
| 문서 수준 | 팀원이 따라 할 수 있는 정도 | 혼자 설치할 수 있는 정도 |
| 운영 책임 | 팀 | 사용자 지원·장애 대응 포함 |

**이유**: 2026 창의적 종합설계 경진대회 접수 마감(10/29 15:00)까지 5일이 남아 있고, 심사 배점상 지금 필요한 것은
기능 확장이 아니라 보고서·영상·정량 성과 정리다. 또한 현재 서버 API에는 인증이 없고 DB 포트가 열려 있어,
남의 클라우드 비용 데이터를 받는 구성은 안전하게 열 수 없다.
"새 계정에서 재현됨"(단계 4)은 완성도와 사업화 가능성의 근거로 사용한다.

**이 결정이 바꾸는 것**
- 단계 3의 3-1(API 인증)·3-6(HTTPS)은 **후순위(외부 배포 전환 시 필수)**. 3-2(DB 포트 제한)는 본선 온라인 중계에서
  서버 주소가 노출될 수 있어 본선 전에 하는 것을 권장한다.
- 단계 2는 팀원이 따라 할 수 있는 수준(서버 설치 스크립트, 수집기 설치 가이드, 사전 점검)으로 범위를 줄인다.
- 외부 배포로 전환하는 조건: 실제로 쓰겠다는 외부 기업·기관의 등장, 산학협력형 확인서를 받을 수 있게 된 경우,
  본선에서 실사용 검증이 평가 포인트가 되는 경우.

**대회 일정과의 관계**
- ~10/29: 코드 작업은 멈추고 보고서·영상·수치 정리 (기능 추가 없음)
- 11/2~11/9 예선 전후: 단계 2 중 필요한 것만
- 11/13 본선 전(진출 시): 3-2 DB 포트 제한 등 노출 대비 정리
- 대회 이후: 단계 4 클린룸 검증, 필요 시 외부 배포용 확장

### 전제 (결정 필요 시 이 문서를 먼저 고친다)

- **클라우드당 수집 대상 VM 1대** 가정을 유지한다. (현재 코드가 `INSTANCE_NAME`, `--instance-id`, `AZURE_VM_NAME` 등 단일 VM 기준)
- 서버는 사용자가 직접 준비한 VM 한 대에서 Docker Compose로 운영한다.

---

## 현황 진단

### A. 이 환경에서만 동작하게 만드는 하드코딩 (코드)

| # | 파일 | 위치 | 내용 | 영향 |
|---|---|---|---|---|
| 1 | `collectors/aws_exporter.py` | `REGION` | `"ap-northeast-2"` | 다른 리전이면 수집 실패 |
| 2 | `collectors/aws_exporter.py` | `--instance-id` 기본값 | `i-05f7cdc5c5183e2ae` | 새 계정에 없는 인스턴스 |
| 3 | `collectors/aws_exporter.py` | 디스크 Dimension | `device=nvme0n1p1` | 인스턴스/AMI에 따라 장치명이 달라 디스크 지표가 비어 있게 됨 |
| 4 | `collectors/aws_exporter.py` | `INSTANCE_SPECS` | t3.micro/small/medium 3종만 | 그 외 타입은 vcpu/ram이 `None` |
| 5 | `collectors/aws_unused_detector.py` | `REGION` | `"ap-northeast-2"` | 위와 동일 |
| 6 | `collectors/gcp_exporter.py` | `PROJECT_ID`, `ZONE`, `INSTANCE_NAME` | 우리 프로젝트/존/`finops-test` | 새 프로젝트에서 조회 불가 |
| 7 | `collectors/gcp_exporter.py` | `__main__` 내 `BILLING_ACCOUNT_ID` | 우리 청구 계정 ID | 비용 수집 불가 |
| 8 | `collectors/gcp_exporter.py` | 디스크 필터 | `device="/dev/sda1"` | 디스크 지표가 비어 있게 됨 |
| 9 | `collectors/gcp_unused_detector.py` | `PROJECT_ID`, `REGION`, `ZONE` | 위와 동일 | 위와 동일 |
| 10 | `collectors/azure_exporter.py` | `DEFAULT_REGION` | `"koreacentral"` | 환경변수 `AZURE_REGION`으로 덮어쓸 수 있어 경미 |
| 11 | `server/budget_alert.py` | `MONTHLY_BUDGET` | 클라우드별 50달러 고정 | 환경별 예산 반영 불가 |

### B. 코드는 이식 가능하지만 새 환경에서 빠지는 것 (운영/설정)

| # | 항목 | 현재 상태 | 영향 |
|---|---|---|---|
| 12 | **cron 설정** | README는 "5분/1일 cron 자동화 완료"라고 하지만 **저장소 어디에도 crontab 내용이 없음** (`runbook/`, `collectors/` 모두 없음) | 새 환경에서 무엇을 몇 시에 돌려야 하는지 알 수 없음. 현재 운영 VM의 `crontab -l`을 확보해야 함 |
| 13 | 메모리·디스크 지표 에이전트 | AWS CloudWatch Agent / Azure Log Analytics(DCR) / GCP Ops Agent가 VM에 설치돼 있어야 함. 절차가 runbook 문서에만 있음(Azure는 약 1,950줄) | 에이전트 없으면 CPU만 수집됨 |
| 14 | GCP 비용 | BigQuery billing export 활성화 필요, **과거 데이터 소급 안 됨** | 활성화 시점부터만 쌓임 |
| 15 | `allocation_rules` 초기 데이터 | 스키마에 테이블만 있고 시드 없음 | 새 환경의 서버 VM 자신이 "저활용 → 다운사이즈 추천"으로 잡힐 수 있음 (decisions/0013의 데모 사고와 동일) |
| 16 | Grafana | 대시보드 JSON을 수동 import해야 하고 데이터소스 연결도 수동. 관리자 비밀번호 `admin` 고정 | 새 환경에서 빈 Grafana |
| 17 | `requirements.txt` | GCP 패키지(`google-cloud-*`)가 주석 처리 | GCP 수집기 설치 시 import 실패 |
| 18 | 환경변수 문서 | 코드가 읽는 키 12개가 한 곳에 정리돼 있지 않음 (`.env.example` 없음) | 처음 설치하는 사람이 키를 찾아 헤맴 |

### C. 보안 (다른 사람 계정에 배포하기 전 필수)

| # | 항목 | 현재 상태 |
|---|---|---|
| 19 | 서버 API 인증 | `server/main.py`에서 API 키/토큰 검사 코드를 찾지 못함 (Slack 엔드포인트는 서명 검증 사용). 누구나 `POST /resources` 가능 |
| 20 | DB 포트 | `docker-compose.yml`이 `5432:5432`로 모든 인터페이스에 공개 |
| 21 | 비밀 값 | `.env`는 `.gitignore`에 있음(OK). `.env.example`이 없어 필요한 키가 문서화되지 않음 |

### D. 데이터 의존성 (설치와 무관하게 새 환경에서 발생)

- 이상탐지 학습: 최근 7일, 인스턴스(클라우드)당 20건 미만이면 학습 스킵 (`ml/train.py`)
- 비용 예측: 7일치 미만이면 신뢰도 경고 (`ml/cost_forecast.py`)
- → 새 환경은 **설치 후 며칠간 ML 결과 패널이 비어 있는 것이 정상**. 데모용으로는 `data/synthetic/generate_synthetic.py`(`source='synthetic'` 구분 컬럼 있음)를 쓰되, 실데이터 오염 이력(INC-002)이 있으니 학습에서 분리되는지 확인한다.

---

## Decision

4개 단계로 나눠, **단계마다 독립 브랜치/PR**로 진행한다. 각 단계는 앞 단계가 없어도 기존 환경의 동작을 깨뜨리지 않는 것을 원칙으로 한다.

### 공통 원칙

1. **필수 설정은 기본값 없이 누락 시 명확한 오류로 중단**한다. (우리 프로젝트 ID 같은 값을 기본값으로 남기면, 새 환경에서 조용히 남의 리소스를 조회하다 실패한다.)
2. 따라서 단계 1 반영 전에 **기존 운영 VM(AWS/Azure/GCP/서버)의 `.env`를 먼저 채워둔다.** 코드를 먼저 배포하면 운영 cron이 깨진다.
3. 모든 수집기는 기존처럼 `--dry-run`을 유지하고, 새 환경 검증은 `--dry-run` → 실제 전송 순서로 한다.
4. 커밋/브랜치 규칙은 기존 컨벤션(`feat(...)`, `docs(...)`, `fix(...)`)을 따른다.

---

### 단계 0. 사전 준비 (코드 수정 없음)

| 작업 | 담당 | 완료 기준 |
|---|---|---|
| 운영 중인 3개 VM + 서버 VM에서 `crontab -l` 확보해 기록 | 각 클라우드 담당자(A/B/C) | 실행 주기·명령·로그 경로를 `runbook/`에 정리할 수 있는 원문 확보 |
| 운영 `.env`의 키 목록(값 제외) 수집 | 각 담당자 | 키 이름이 12개 목록과 대조됨 |
| 대상 환경 범위 확정: "팀 내부 재현용"인지 "외부 사용자 배포용"인지 | 팀 | **완료(2026-10-24): 팀 내부 재현 우선.** 위 "대상 결정" 참고 |
| `decisions/` 번호 중복 정리 (`0003` 3개 등) | 누구나 | 번호가 유일 |

### 단계 1. 설정 분리 — "`.env`만 채우면 어느 계정에서든 조회가 된다"

**대상 파일**: `collectors/aws_exporter.py`, `aws_unused_detector.py`, `gcp_exporter.py`, `gcp_unused_detector.py`, `azure_exporter.py`, `azure_unused_detector.py`, `server/budget_alert.py`, `.env.example`(신규), `README.md`, `tests/`

| 작업 | 상세 |
|---|---|
| 1-1 환경변수 도입 | AWS: `AWS_REGION`, `AWS_INSTANCE_ID`. GCP: `GCP_PROJECT_ID`, `GCP_ZONE`, `GCP_INSTANCE_NAME`, `GCP_BILLING_ACCOUNT_ID` (region은 zone에서 파생). Azure는 기존 `AZURE_*` 유지. 예산: `BUDGET_AWS`, `BUDGET_AZURE`, `BUDGET_GCP` (미설정 시 알림 비활성 또는 명시적 기본값) |
| 1-2 디스크 장치 자동화 | AWS `nvme0n1p1`, GCP `/dev/sda1` 하드코딩 대신 환경변수(`AWS_DISK_DEVICE`, `GCP_DISK_DEVICE`) 또는 루트(`/`) 마운트 기준 조회. 기본 동작을 정해 `decisions`에 한 줄 남긴다 |
| 1-3 인스턴스 사양 조회 | AWS `INSTANCE_SPECS` 3종 표를 `describe_instance_types` 조회로 대체(실패 시 기존 표로 폴백). GCP/Azure는 이미 API로 조회 중 |
| 1-4 누락 검증 | 수집기 시작 시 필수 변수를 한 번에 검사해 "빠진 키 목록"을 출력하고 종료 |
| 1-5 `.env.example` | 루트에 클라우드별 섹션(서버 / AWS / Azure / GCP / Slack)으로 작성. 각 키에 용도·예시·필수 여부 주석. 실제 값은 넣지 않음 |
| 1-6 GCP 패키지 | `requirements.txt`의 주석 처리된 `google-cloud-*`를 실제 설치 가능한 버전으로 채움 (GCP 환경에서 확인 필요 — C 담당) |
| 1-7 테스트 | `tests/test_*_exporter.py`가 하드코딩 값에 의존하는지 확인하고, 환경변수 주입 방식으로 수정 |

**완료 기준**
- `git grep`으로 우리 식별자(`i-05f7…`, `project-3f80…`, `0175A5-…`, `ap-northeast-2` 기본값 등) 검색 시 코드에 0건
- 운영 환경 3곳에서 `.env`만 채운 상태로 `--dry-run` 출력이 기존과 동일
- 필수 키를 일부러 비웠을 때 어떤 키가 빠졌는지 알려주고 종료

**위험**: 운영 cron 중단 → 공통 원칙 2번(`.env` 선배포)으로 대응. 롤백은 PR revert.

### 단계 2. 설치 자동화 — "스크립트 몇 개로 새 VM이 수집을 시작한다"

**대상 파일**: `scripts/`(신규), `runbook/new-environment-setup.md`(신규), 에이전트 설정 템플릿(신규)

| 작업 | 상세 |
|---|---|
| 2-1 cron을 코드로 | 단계 0에서 확보한 crontab을 `scripts/crontab.*.example`로 저장하고, 설치 스크립트가 경로를 치환해 등록. 수집(5분/1일), 미사용 탐지, ML 배치(`train`/`anomaly_detector`/`recommend`/`cost_forecast`), `budget_alert` 포함 |
| 2-2 서버 설치 | `scripts/install_server.sh`: Docker 설치 확인 → `.env` 필수 키 검사 → `docker compose up -d --build` → `/health` 확인 |
| 2-3 AWS 수집기 설치 | `scripts/install_collector_aws.sh`: CloudWatch Agent 설치 + **`config.json`을 저장소에 템플릿으로 커밋**(현재는 runbook에만 있음) → venv/requirements → cron 등록 → `--dry-run` 검증 |
| 2-4 GCP 수집기 설치 | Ops Agent 설치 → venv/requirements → cron → 검증. BigQuery billing export는 **콘솔 수동 단계**임을 명시 |
| 2-5 Azure 수집기 설치 | Azure Monitor Agent + DCR/Log Analytics 연결 절차를 `az` CLI 스크립트로 축약(현재 runbook 약 1,950줄 → 핵심 절차만). 서비스 프린시펄 생성 절차 포함 |
| 2-6 사전 점검 스크립트 | `scripts/check_prereqs.py`: 자격증명 유효, 대상 VM 조회 가능, 에이전트 지표(메모리·디스크) 존재, 서버 `/health` 도달 여부를 항목별 OK/FAIL로 출력 |
| 2-7 최소 권한 문서 | 코드가 실제 호출하는 API 기준으로 IAM 정책/역할 목록 확정. 후보(구현 시 코드로 재검증): AWS `cloudwatch:GetMetricStatistics`, `ec2:Describe*`, `ce:GetCostAndUsage`, `pricing:GetProducts` / Azure `Monitoring Reader`, `Reader`, `Cost Management Reader`, Log Analytics 읽기 / GCP `monitoring.viewer`, `compute.viewer`, BigQuery 조회·작업 권한 |
| 2-9 Python 버전 | AWS EC2의 Python이 3.9라 boto3 지원 종료(2026-04-29) 경고가 cron 로그에 매번 쌓이고 있음. README 전제(3.11+)에 맞춰 설치 스크립트가 3.11 이상 가상환경을 만들게 한다 |
| 2-8 runbook 통합 | `runbook/new-environment-setup.md` 하나로 "서버 → 클라우드별 수집기 → 검증" 순서의 처음부터 끝까지 절차 작성. 기존 runbook은 상세 참고용으로 링크 |

**완료 기준**
- 빈 VM에서 문서 순서대로 따라 했을 때 수동 개입이 "콘솔에서 해야만 하는 항목"(권한 부여, billing export 활성화)으로 한정
- `check_prereqs.py`가 전부 OK
- 5분 뒤 서버 `GET /resources?cloud=<CLOUD>`에 데이터가 들어옴

### 단계 3. 운영 하드닝 — "다른 사람 환경에 올려도 안전하고 대시보드가 바로 나온다"

> 대상 결정(팀 내부 재현 우선)에 따라 **3-1, 3-6은 후순위**(외부 배포 전환 시 필수), **3-2는 본선 전 권장**, 나머지는 단계 2 이후 필요한 만큼 진행한다.

| 작업 | 상세 |
|---|---|
| 3-1 API 인증 | 쓰기 엔드포인트(`POST /resources`, `/costs`, `/unused-resources`)에 `X-API-Key` 검사 추가, `collectors/server_client.py`와 각 수집기가 헤더를 붙임. 키는 `.env`(`API_KEY`). 읽기 엔드포인트와 Slack 엔드포인트는 현행 유지 후 필요 시 검토 |
| 3-2 DB 포트 | `docker-compose.yml`을 `127.0.0.1:5432:5432`로 제한(외부 접속 필요 시 SSH 터널 안내) |
| 3-3 Grafana 프로비저닝 | `grafana/provisioning/`에 PostgreSQL 데이터소스와 대시보드 자동 로드 추가. `dashboard/dashboard.json`의 데이터소스 uid 의존 제거(변수화). 관리자 비밀번호를 `.env`로 |
| 3-4 시드 데이터 | `db/seed.example.sql` 또는 설치 스크립트가 서버 VM 자신을 `allocation_rules`에 `CloudFit-Core-Infra`로 등록하도록 안내/자동화 (decisions/0013 재발 방지) |
| 3-5 CI | GitHub Actions로 `pytest` + 하드코딩 식별자 재유입 검사(`git grep`) + `docker compose config` 검증. 현재 저장소에는 CI가 없음 |
| 3-6 (선택) HTTPS | 서버를 리버스 프록시(Caddy 등) 뒤에 두는 절차를 runbook에 추가 |

**완료 기준**
- 키 없이 `POST /resources` 시 401, 키 있으면 201
- 외부 IP에서 5432 접속 불가
- 새 환경에서 `docker compose up` 후 Grafana에 대시보드가 이미 로드돼 있음

**위험**: 3-1은 수집기와 서버를 동시에 바꾸는 변경이라 **서버를 "키 없으면 경고만 → 이후 강제"** 두 단계로 배포하지 않으면 운영 수집이 끊긴다.

### 단계 4. 새 계정 검증 및 (선택) 확장

| 작업 | 상세 |
|---|---|
| 4-1 클린룸 검증 | 팀원이 **완전히 새 계정/프로젝트**에서 `runbook/new-environment-setup.md`만 보고 3개 클라우드 + 서버를 설치. 막힌 지점을 문서에 반영하고 단계 1~3으로 되돌려 보완 |
| 4-2 데모 데이터 | 실데이터가 쌓이기 전 대시보드 시연용 합성 데이터 투입 절차 문서화 (`source` 분리 확인) |
| 4-3 (후속 후보) 다중 VM 자동 발견 | 클라우드당 단일 VM 전제 제거 |
| 4-4 (후속 후보) IaC | Terraform으로 VM·권한·에이전트까지 생성 |

**검증 시 비용 주의**: 새 VM(예: t3.micro, e2-micro, B 시리즈), 로그 수집, BigQuery 쿼리, Cost API 호출에 비용이 발생한다. 검증 후 리소스를 삭제하고, 무료 크레딧과 예산 알림을 먼저 설정한다.

---

## 진행 순서와 브랜치

```
단계 0 (사전, 코드 없음)
  → 단계 1  feature/portable-config      → PR → main
  → 단계 2  feature/portable-installer   → PR → main   (단계 1 병합 후)
  → 단계 3  feature/portable-hardening   → PR → main   (단계 2와 병렬 가능: 3-1 제외)
  → 단계 4  새 계정 검증 (문서 수정 PR)
```

- 단계 1은 모든 수집기를 건드리므로 **클라우드별로 PR을 쪼개는 방안**(AWS/GCP/Azure 각 1개)도 가능. 충돌 위험이 낮은 순서: Azure(이미 환경변수 방식) → AWS → GCP.
- 각 PR에는 "기존 환경에서의 `--dry-run` 결과가 동일함"을 증거로 첨부한다.

## Why

- 설정 분리(1)가 가장 작고 효과가 크며, 이후 단계의 전제다.
- 설치 자동화(2)가 없으면 에이전트·cron 같은 "코드 밖 설정"이 사람마다 달라 재현되지 않는다. 특히 cron은 현재 저장소에 없다.
- 하드닝(3)은 우리 팀 밖으로 나갈 때 필수다. 팀 내부 재현용이면 3-1, 3-6은 후순위로 미룰 수 있다.
- 검증(4)은 "우리 계정에서 되던 것"과 "새 계정에서 되는 것"의 차이를 드러내는 유일한 방법이다. 코드만 읽어서는 IAM 권한 누락·에이전트 설정 차이를 다 찾지 못한다.

## 대안과의 비교

| 대안 | 장점 | 단점 | 채택 여부 |
|---|---|---|---|
| 현행 유지 + 환경마다 코드 수정 | 작업 0 | 환경마다 포크가 생겨 유지보수 불가 | 미채택 |
| **설정 분리 + 설치 스크립트 (채택)** | 비용 대비 효과 큼, 현재 구조 유지 | 에이전트·권한은 콘솔 수동 단계가 남음 | **채택** |
| 처음부터 Terraform/Ansible | 가장 재현성 높음 | 3개 클라우드 분량이 크고 일정 부담. 설정 분리가 선행돼야 함 | 후속 후보 |
| SaaS형(우리가 서버 운영, 고객은 에이전트만) | 고객 설치 쉬움 | 멀티 테넌트·인증·격리 설계가 필요해 범위가 다름 | 범위 밖 |

## 열린 질문 (진행 전 팀 확인)

1. ~~대상이 "팀 내부 재현/시연용"인가, "외부 사용자 배포용"인가?~~ → **결정: 팀 내부 재현 우선 (2026-10-24)**. 외부 배포는 확장 계획
2. 클라우드당 VM 1대 전제를 유지해도 되는가?
3. 운영 중인 `.env`와 crontab은 누가 언제 공유하는가? (단계 0)
4. GCP `google-cloud-*` 패키지 버전은 C 담당이 GCP 환경에서 확인 가능한가?
5. 새 계정 검증용 크레딧/예산은 누구 계정을 쓰는가?

## Result

- [ ] 단계 0: crontab·`.env` 키 확보, 범위 확정, `decisions/` 번호 정리
  - [x] AWS·GCP crontab 확보 → `runbook/crontab-reference.md`
  - [x] AWS·GCP `.env` 키 이름 확보 (AWS: SLACK_WEBHOOK_URL, DB_PASSWORD, DATABASE_URL, GRAFANA_ADMIN_PASSWORD, SLACK_SIGNING_SECRET / GCP: SERVER_URL, SLACK_WEBHOOK_URL)
  - [x] GCP 패키지 버전 확보 (api-python-client 2.198.0 / bigquery 3.42.2 / monitoring 2.31.0)
  - [ ] Azure VM crontab·`.env` 키 (B 담당, 대기 중)
  - [x] GCP `google-cloud-compute` 버전 확보 (1.52.0, `gcp_unused_detector.py`가 import)
  - [x] 대상 범위 확정(열린 질문 1): 팀 내부 재현 우선 (2026-10-24)
  - [ ] 열린 질문 2(클라우드당 VM 1대 전제 유지), `decisions/` 번호 중복 정리
  - [x] 발견·수정: GCP 미사용 탐지 cron이 시스템 `python3`로 실행돼 `ModuleNotFoundError: dotenv`로 실패하고 있었음 → 가상환경 파이썬으로 교체 (2026-10-24, `--dry-run` 정상). 내일 09:15 이후 `logs/unused_resource.log`로 최종 확인
  - 확인 필요: AWS `.env`에는 `GRAFANA_ADMIN_PASSWORD`가 있지만 저장소의 `docker-compose.yml`은 Grafana 비밀번호를 `admin`으로 고정하고 있다. EC2의 compose 파일이 저장소와 다르게 수정돼 있을 수 있다 (`git status`로 확인). 단계 3에서 정리.
- [~] 단계 1: 설정 분리, `.env.example`, 필수 키 검증, 테스트 수정 — **AWS·GCP·예산 구현·병합 완료(PR #7), AWS EC2·GCP VM 실환경 검증 완료(2026-10-24). 남은 것은 Azure 점검.** Azure는 이미 환경변수 방식이라 `.env.example`에만 반영
  - [x] `collectors/cloud_config.py` (필수 키 일괄 검증, 종료 코드 2), `.env.example`
  - [x] AWS: `AWS_REGION`, `AWS_INSTANCE_ID`, 디스크 Dimension(`AWS_DISK_DEVICE`/`AWS_DISK_FSTYPE`; `fstype=xfs`도 하드코딩이었음), 인스턴스 사양 API 조회(폴백 표 유지, `ec2:DescribeInstanceTypes` 권한 추가 필요)
  - [x] GCP: `GCP_PROJECT_ID`/`GCP_ZONE`/`GCP_INSTANCE_NAME`/`GCP_BILLING_ACCOUNT_ID`, `GCP_DISK_DEVICE`, 머신 사양 API 조회(폴백 표 유지, `compute.machineTypes.get` 권한 추가 필요)
  - [x] 예산: `BUDGET_AWS`/`BUDGET_AZURE`/`BUDGET_GCP` (미설정 시 건너뜀. 기존에는 클라우드별 50달러 고정이었으므로 **운영 서버 `.env`에 `BUDGET_*=50`을 넣어야 기존 동작 유지**)
  - [x] 테스트 16개 추가. 기존 Azure 테스트 5개 실패는 `main`에도 있던 것(이 작업과 무관)
  - [x] 운영 VM `.env`에 새 키 선반영 → 그 후 병합 (공통 원칙 2). AWS EC2·GCP VM 모두 선반영 후 PR #7 병합
  - [x] 실환경 검증 (2026-10-24): 두 VM에서 `--dry-run` 정상. `ram_gb`가 `1`에서 `1.0`으로 바뀐 것으로 사양 API 조회 경로와 `.env` 설정 읽기를 확인
  - [ ] 수집 cron이 새 코드로 계속 도는지 `logs/aws_resource.log`, `logs/gcp_resource.log`로 확인
  - [x] `google-cloud-compute==1.52.0` 반영
  - [ ] Azure 수집기 점검
- [ ] 단계 2: 설치 스크립트, cron 코드화, 사전 점검, 권한 문서, 통합 runbook
- [ ] 단계 3: API 인증, DB 포트 제한, Grafana 프로비저닝, 시드, CI
- [ ] 단계 4: 새 계정 클린룸 검증 (AWS / Azure / GCP / 서버)
