# 멀티클라우드 FinOps 프로젝트 운영 지침
 
> 혼자가 아니라 팀(3명) + AI와 함께 진행하지만,
> **이해 없이 넘어가지 않는다** 는 원칙은 동일하게 유지한다.
 
---
 
## 1. 작업 원칙
 
- 하루 1개 **Change → Validate → Fail/Recover → Artifact → Evidence** 루프를 기본으로 한다
- "동작했다"로 끝내지 않는다. **왜 동작했는지 / 실패 시 어떤 증상이 나타나는지**까지 기록한다
- 설정 변경은 반드시 **검증 명령어 실행 후 커밋**한다
- 팀원 간 작업은 **같은 검증 기준**을 공유한다. "내 쪽에서는 됐어요"는 증거가 아니다
- 각자 담당 클라우드가 달라도 **공통 데이터 형식은 항상 일치**해야 한다
---
 
## 2. 매일 시작 루틴
 
### Step 1 — 전날 복습 (1~2개 질문)
AI가 전날 핵심 내용 관련 질문 1~2개를 한다.
답 못하면 → 전날 diary 다시 읽고 이해한 뒤 시작한다.
 
### Step 2 — 오늘 예측 (한 줄 선언)
아래 3개 질문에 한 줄씩 답하고 시작한다.
틀려도 된다. 짧아도 된다. **말 못하면 → 먼저 이해하고 시작한다.**
 
```
1. 오늘 왜 이걸 하는가?
   → 이 작업이 전체 파이프라인에서 어떤 역할인지 한 줄로.
 
2. 이 기술/방법 말고 다른 선택지도 있었나?
   → 대안을 한 개 이상 떠올려본다.
 
3. 잘못되면 어떤 증상이 나타날까?
   → 미리 예상해보는 것. 틀려도 괜찮다.
```
 
---
 
## 3. 팀 협업 원칙
 
### 역할 분담
| 팀원 | 담당 클라우드 | 주요 책임 |
|------|-------------|-----------|
| A | AWS | CloudWatch, Cost Explorer, boto3 수집기 |
| B | Azure | Azure Monitor, Cost Management, azure-sdk 수집기 |
| C | GCP | Cloud Monitoring, Cloud Billing, google-cloud 수집기 |
 
### 공통 규칙
- 각자 만든 수집 모듈은 **공통 스키마**를 준수한다 (컬럼명, 단위, 타임스탬프 형식)
- 코드 변경 사항은 `main` 브랜치에 직접 push하지 않는다. **PR(Pull Request)** 후 팀원 1명 이상 리뷰
- 막히면 혼자 2시간 이상 붙잡지 않는다. 즉시 팀 채팅에 에러 메시지와 함께 공유한다
- 주차 마지막 날에는 팀 전체가 체크포인트를 함께 확인한다
- WBS는 **2주마다** 팀원 전원이 갱신한다
### 브랜치 전략
```
main          → 검증 완료된 코드만
dev           → 개발 통합 브랜치
feature/A-aws → A의 AWS 수집기 개발
feature/B-azure → B의 Azure 수집기 개발
feature/C-gcp → C의 GCP 수집기 개발
```
 
---
 
## 4. 문서화 규칙
 
### Diary
- 파일명: `diary/YYYY-MM-DD-dayXX.md`
- 팀원 각자 작성 (같은 날 작업해도 각자 기록)
- 구조:
  - 오늘 목표
  - 오늘 한 일
  - 왜 이 기술/방법을 선택했는가 (표)
  - 오늘 처음 안 사실 (몰랐던 것 → 알게 된 것)
  - 결과·증거 (캡처 링크 포함)
  - 막힌 점
  - 혼자 다시 할 수 있나? (커밋 전 자문)
### Runbook
- 파일명: `runbook/{주제}.md`
- 누적 참고 문서. **작업할 때마다 업데이트**한다
- 예시:
  - `runbook/aws-collector-setup.md`
  - `runbook/db-schema-migration.md`
  - `runbook/grafana-setup.md`
### Incident
- 파일명: `incidents/INC-XXX.md`
- 구조: Summary / Severity / Impact / Detection / Timeline / Symptoms / Root Cause / Recovery / Prevention / Evidence
- **장애는 직접 재현하고, 재현 명령어를 반드시 포함한다**
- Severity 기준:
  - P1: 전체 수집 파이프라인 중단
  - P2: 특정 CSP 수집 중단
  - P3: 분석/추천 결과 오류
  - P4: 대시보드 표시 오류
### Decisions
- 파일명: `decisions/XXXX-{주제}.md`
- 새로운 기술 선택이나 설계 결정이 생기면 반드시 작성한다
- 구조: Context / Decision / Why / 대안과의 비교 / Result
- 예시:
  - `decisions/0001-db-selection.md` (PostgreSQL vs TimescaleDB)
  - `decisions/0002-ml-model-selection.md` (Isolation Forest vs LSTM)
  - `decisions/0003-common-schema.md` (공통 스키마 설계 근거)
---
 
## 5. Diary 고정 섹션 템플릿
 
```markdown
# YYYY-MM-DD — Day XX
 
## 오늘 목표
- 
 
## 오늘 한 일
- 
 
## 왜 이 기술/방법을 선택했는가
| 항목 | 선택한 것 | 대안 | 선택 이유 |
|------|-----------|------|-----------|
| ... | ... | ... | ... |
 
## 오늘 처음 안 사실
| 몰랐던 것 | 알게 된 것 | 왜 그렇게 되는지 |
|-----------|-----------|----------------|
| ... | ... | ... |
 
## 결과·증거
- 캡처: `evidence/dayXX-{설명}.png`
 
## 막힌 점
- 
 
## 혼자 다시 할 수 있나? (커밋 전 자문)
- [ ] Yes → 커밋
- [ ] No → 막힌 부분을 위 섹션에 기록 후 커밋
```
 
---
 
## 6. 커밋 규칙
 
커밋 메시지는 **한국어**로 작성한다.
 
| prefix | 용도 |
|--------|------|
| feat | 새로운 기능 |
| fix | 버그 수정 |
| docs | 문서 수정 |
| refactor | 코드 리팩토링 |
| chore | 그 외 자잘한 수정 |
| build | 빌드 관련 파일 수정 |
| ci | CI 관련 설정 수정 |
| style | 코드 스타일/포맷 |
| test | 테스트 코드 수정 |
| perf | 성능 개선 |
 
커밋 예시:
```
feat(aws-collector): CloudWatch CPU/메모리 수집 모듈 구현
fix(azure-collector): 인증 토큰 만료 처리 예외 처리 추가
docs(runbook): AWS 수집기 설치 및 실행 절차 작성
docs(decisions): ML 모델 선택 근거 기록 (Isolation Forest)
```
 
evidence 파일은 커밋 시 이름과 함께 명시한다.
예) `evidence/day05-aws-cpu-collect-ok.png`
 
---
 
## 7. 검증 원칙
 
변경 후 반드시 아래 중 하나 이상 실행한다.
 
```bash
# 서버/컨테이너 상태 확인
docker ps
docker logs {컨테이너명}
systemctl status {서비스명}
 
# API 응답 확인
curl -s http://localhost:8000/resources | python3 -m json.tool
curl -s http://localhost:8000/costs
 
# DB 데이터 확인
psql -U {user} -d {db} -c "SELECT COUNT(*) FROM resource_metrics;"
 
# 수집기 동작 확인
python3 collectors/aws_exporter.py --dry-run
python3 collectors/azure_exporter.py --dry-run
python3 collectors/gcp_exporter.py --dry-run
```
 
검증 결과는 **Diary 또는 Incident의 Evidence 항목에 반드시 기록**한다.
 
---
 
## 8. 산출물 기준
 
- 작업 1개 = **커밋 1개 이상 + 문서 1개 이상**
- 스크린샷 또는 터미널 출력 캡처를 Evidence로 남긴다
- 주차 마지막 날에는 **Week 회고**를 작성한다
### Week 회고 구조
```markdown
# Week XX 회고 (날짜)
 
## 완료한 것
## 완료 못한 것 + 이유
## 배운 것
## 다음 주 목표
## 팀 이슈 (있으면)
```
 
---
 
## 9. AI 활용 원칙
 
- 문서 초안 / 코드 초안은 AI를 활용해도 된다
- 단, 올리기 전에 **반드시 이해 검증**을 거친다
- 검증 방식: AI가 핵심 내용 관련 질문 2~3개를 하고, 성민이가 답한다
- 답하지 못한 항목은 다시 읽고 이해한 뒤 올린다
- **"초안은 AI가, 이해와 검증은 내가"** 원칙을 유지한다
- AI가 짜준 코드는 한 줄씩 읽으면서 **무슨 코드인지 설명할 수 있을 때** 커밋한다
---
 
## 10. 응답 방식 원칙 (AI와 협업 시)
 
- 작업 내용을 한 번에 전부 제시하지 않는다
- 매 응답은 **현재 단계에서 해야 할 것 하나에 집중**한다
- 단계마다 왜 이걸 하는지 한 줄로 설명한다
- 흐름:
  1. 매일 시작 루틴 (복습 질문 + 오늘 예측)
  2. 오늘 할 작업 목표 제시
  3. 성민이 실행 → 결과 공유
  4. 결과 확인 후 다음 단계 안내
  5. 완료되면 Diary / Decisions / Incident 문서 초안 제시
---
 
## 11. 증거 캡처 원칙
 
### 필수 캡처 타이밍
 
| 타이밍 | 이유 |
|--------|------|
| 장애 발생 직후 | 증상과 에러 메시지가 사라지기 전에 확보 |
| 복구 완료 직후 | 정상 상태로 돌아왔음을 증명 |
 
**"망가진 상태"** 와 **"고친 상태"** 두 장은 항상 있어야 한다.
 
### 캡처 대상 기준
 
아래 중 하나라도 해당하면 캡처한다.
 
- 에러 메시지가 터미널에 출력된 경우
- `docker ps`, `curl`, `psql` 등으로 비정상 상태가 확인된 경우
- 수집 데이터가 DB에 처음 쌓이는 것을 확인한 경우
- 분석 결과 / ML 탐지 결과가 처음 출력된 경우
- Incident 문서의 Evidence 항목에 들어갈 내용인 경우
### 파일명 규칙
 
```
evidence/dayNN-{내용}-{상태}.png
 
예시:
evidence/day01-aws-iam-setup-ok.png
evidence/day03-cpu-collect-first-ok.png
evidence/day10-db-insert-fail.png
evidence/day10-db-insert-recovery-ok.png
```
 
### 캡처를 놓쳤을 때
 
터미널 스크롤로 복원 가능하면 그대로 캡처한다.
스크롤로 복원이 안 되면 **재현 명령어를 다시 실행해서 캡처**한다.
재현이 어려운 경우 Incident Evidence 항목에 `"캡처 누락"` 으로 명시한다.
 
---
 
## 12. 기술 선택 근거 — "왜 이걸 썼는가" 빠른 참고
 
새로운 기술 선택 시 아래를 참고해서 **내 말로** 써본다.
 
### boto3 (AWS SDK)
- AWS 공식 Python SDK로 CloudWatch, Cost Explorer, EC2 등 모든 AWS 서비스를 코드로 제어할 수 있다
- 인증은 IAM Access Key 또는 IAM Role로 처리한다
- **대안**: AWS CLI (자동화 불편), AWS SDK Java/Go (언어 통일 불가)
### CloudWatch
- EC2 인스턴스의 CPU/네트워크/디스크 메트릭을 5분 간격으로 자동 수집한다
- boto3의 `get_metric_statistics`로 특정 기간 데이터를 가져올 수 있다
- **대안**: Prometheus (별도 서버 필요, 이 프로젝트에서는 수집기 역할이 겹침)
### Cost Explorer API
- AWS에서 서비스/계정/날짜별 비용을 코드로 조회할 수 있다
- `boto3.client('ce')`로 호출하며, 일별/월별/서비스별 필터가 가능하다
- **대안**: AWS 콘솔 수동 확인 (자동화 불가)
### Azure Monitor SDK
- `azure-mgmt-monitor`로 VM의 CPU/메모리/디스크 메트릭을 가져온다
- 인증은 Service Principal(서비스 주체) + ClientSecretCredential로 처리한다
- **대안**: Azure CLI (자동화 불편)
### GCP Cloud Monitoring
- `google-cloud-monitoring` 라이브러리로 GCE 인스턴스 메트릭을 가져온다
- 서비스 계정 JSON 키로 인증한다
- **대안**: GCP 콘솔 수동 확인 (자동화 불가)
### FastAPI
- Python 기반 REST API 서버로 Swagger 문서가 자동 생성된다 (`/docs`)
- async 지원으로 여러 수집기 요청을 동시에 처리할 수 있다
- **대안**: Flask (Swagger 자동 생성 없음), Django (너무 무거움)
### PostgreSQL
- 관계형 DB로 자원/비용 데이터를 구조적으로 저장한다
- 인덱스 설계로 시계열 조회 성능을 높일 수 있다
- **대안**: MySQL (JSON 지원 약함), TimescaleDB (학습 곡선 높음, 추후 확장 옵션)
### Isolation Forest (ML 이상탐지)
- scikit-learn 구현체로 비지도 학습 기반 이상 탐지가 가능하다
- 정상 데이터만 있어도 학습이 가능하고, 코드가 몇 줄 안 된다
- **대안**: LSTM Autoencoder (더 강력하지만 학습 시간 오래 걸리고 구현 복잡)
### Grafana
- 시계열 데이터 시각화에 특화되어 있고, Prometheus/PostgreSQL 모두 데이터소스로 연결된다
- 대시보드를 JSON으로 export해서 GitHub에 올릴 수 있다
- **대안**: 직접 만든 웹 프론트 (개발 시간 많이 필요)
### Docker / Docker Compose
- 개발 환경을 파일로 정의해서 팀원 전체가 동일한 환경에서 실행할 수 있다
- `docker compose up` 한 줄로 전체 환경을 재현할 수 있다
- **대안**: 로컬 직접 설치 (환경 오염 위험, 팀원 간 환경 불일치)
### stress-ng
- 리눅스 인스턴스에 CPU/메모리 부하를 인위적으로 만들어 테스트 패턴 데이터를 생성한다
- `stress-ng --cpu 2 --timeout 300s` 형태로 쉽게 사용할 수 있다
- **대안**: 직접 부하 스크립트 작성 (시간 낭비)
---
 
## 13. 폴더 구조
 
```
멀티클라우드-finops/
├── collectors/
│   ├── aws_exporter.py
│   ├── azure_exporter.py
│   └── gcp_exporter.py
├── server/
│   ├── main.py          # FastAPI 앱
│   └── models.py        # DB 모델
├── db/
│   └── schema.sql
├── ml/
│   ├── anomaly_detector.py
│   └── train.py
├── dashboard/
│   └── dashboard.json   # Grafana 대시보드
├── data/
│   ├── synthetic/       # 합성 데이터 생성기
│   └── external/        # 외부 데이터셋 변환본
├── diary/               # 날짜별 작업 일지
├── runbook/             # 운영 참고 문서
├── incidents/           # 장애 기록
├── decisions/           # 기술 결정 기록
├── evidence/            # 캡처 이미지
├── docker-compose.yml
└── README.md
```

### 폴더별 상세 설명

**`collectors/`**
- AWS / Azure / GCP 각자 수집 모듈 코드 올리는 곳
- `aws_exporter.py`, `azure_exporter.py`, `gcp_exporter.py`

**`server/`**
- 중앙 통합 서버 코드 (FastAPI)
- 수집기들이 데이터를 여기로 보내고, 대시보드는 여기서 데이터를 가져감

**`db/`**
- DB 스키마 파일 (`schema.sql`)
- 테이블 구조 바뀌면 여기 업데이트

**`ml/`**
- 이상탐지 ML 모델 코드
- 학습 코드(`train.py`)랑 추론 코드(`anomaly_detector.py`)

**`dashboard/`**
- Grafana 대시보드 설정 파일 (`dashboard.json`)
- 대시보드 구성 바뀌면 JSON export해서 여기 올리기

**`data/`**
- 합성 데이터 생성기 + 외부 데이터셋 변환본 저장 폴더

**`diary/`**
- 각자 작업 후 일지 올리는 곳
- 파일명: `YYYY-MM-DD-dayXX-{이름}.md`

**`evidence/`**
- 터미널 캡처, 성공/실패 스크린샷 올리는 곳
- 파일명: `dayNN-{내용}-{상태}.png`

**`runbook/`**
- 설치/실행/복구 절차 문서
- 각자 담당 클라우드 세팅 방법 여기 정리

**`incidents/`**
- 장애 발생하면 기록하는 곳
- 파일명: `INC-001.md`

**`decisions/`**
- 기술 선택 이유 기록
- 예: "왜 PostgreSQL 썼는가", "왜 Isolation Forest 썼는가"

**`README.md`**
- 프로젝트 전체 설명
- 나중에 GitHub 공개할 때 보이는 메인 문서