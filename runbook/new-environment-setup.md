# 새 환경 설치 가이드 (팀 내부 재현용)

> 대상: 팀원이 **새 AWS / Azure / GCP 계정 또는 새 VM**에서 CloudFit 전체를 다시 만들 때.
> 범위 결정은 `decisions/0015-portable-deployment-plan.md` (팀 내부 재현 우선, 외부 배포는 확장 계획).
> 클라우드별 상세 절차(콘솔 화면, 트러블슈팅)는 기존 runbook을 참고한다:
> `aws-collector-setup.md`, `gcp-collector-setup.md`, `azure-collector-setup-1~3.md`, `server-setup.md`

## 0. 전체 그림

```
[AWS 수집 VM]   --\
[Azure 수집 VM] ---+--(HTTP 8000)--> [서버 VM: API + DB + Grafana + ML 배치 cron] --> Slack
[GCP 수집 VM]   --/
```

| 역할 | 개수 | 하는 일 | 설치 스크립트 |
|---|---|---|---|
| 서버 VM | 1대 | Docker Compose(DB, API, Grafana), ML·알림 배치 cron | `scripts/install_server.sh` |
| 수집 VM | 클라우드당 1대 | 자원 지표(5분)·비용·미사용 리소스 수집 후 서버로 전송 | `scripts/install_collector.sh <aws\|gcp\|azure>` |

서버 VM이 AWS의 수집 VM을 겸해도 된다(현재 운영 구성). 그 경우 두 스크립트를 모두 실행한다.

**순서는 꼭 지킨다: 서버 → 수집 VM.** 수집기는 서버가 떠 있어야 데이터를 보낼 수 있다.

## 1. 준비물

- 각 VM에 SSH 접속 가능, 저장소를 받을 수 있는 인터넷 (`git clone`)
- 서버 VM: Docker (`docker compose` 또는 `docker-compose`)
- 수집 VM: Python 3.10 이상 권장 (3.9는 boto3 지원이 끝나 경고가 계속 나온다)
  - Amazon Linux: `sudo dnf install -y python3.11` / Ubuntu: `sudo apt install -y python3.11 python3.11-venv`
- 수집 대상 VM은 **켜져 있어야** 한다 (꺼져 있으면 CPU 지표가 비어 점검이 실패한다)
- Slack Incoming Webhook URL (알림을 쓸 때)

## 2. 서버 VM

```bash
git clone https://github.com/acau7143/CloudFit.git
cd CloudFit
cp .env.example .env
```

`.env`의 **[서버/DB]** 섹션을 채운다 (`DB_PASSWORD`, `DATABASE_URL`, `GRAFANA_ADMIN_PASSWORD`, 필요하면 `SLACK_*`, `BUDGET_*`).
`DATABASE_URL`의 비밀번호 부분은 `DB_PASSWORD`와 같은 값으로 쓴다.

```bash
bash scripts/install_server.sh            # 컨테이너 기동 + 패키지 설치 + 점검 + cron 미리보기
bash scripts/install_server.sh --apply    # 점검이 통과하면 ML 배치 cron 등록
```

- `--apply` 전에는 crontab을 바꾸지 않는다. 등록하면 기존 crontab은 `~/crontab.backup.<시각>`에 백업된다.
- 방화벽/보안그룹에서 **8000 포트를 수집 VM의 IP에만** 연다. Grafana(3000)는 본인 IP에만 연다.
- 확인: `curl http://localhost:8000/health` → `{"status":"ok"}`

**Grafana 연결** (처음 한 번): `http://<서버>:3000` 로그인 → 데이터소스에 PostgreSQL 추가
(호스트 `db:5432`, DB `finops_db`, 사용자 `finops`, 비밀번호 `DB_PASSWORD` 값) → `dashboard/dashboard.json` 가져오기.
패널이 비어 있으면 각 패널의 데이터소스가 새 PostgreSQL로 잡혔는지 확인한다.

## 3. 수집 VM — AWS

**3-1. 권한 (EC2 인스턴스 역할)**: 키를 `.env`에 넣지 않고 EC2에 IAM 역할을 연결한다. 아래 정책 + 에이전트용 관리형 정책 `CloudWatchAgentServerPolicy`.

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "cloudwatch:GetMetricStatistics",
      "ec2:DescribeInstances", "ec2:DescribeInstanceTypes",
      "ec2:DescribeVolumes", "ec2:DescribeAddresses",
      "ce:GetCostAndUsage"
    ],
    "Resource": "*"
  }]
}
```

`ec2:DescribeInstanceTypes`는 선택이다 (없으면 vCPU/RAM을 내장 표로 채운다). Cost Explorer는 계정에서 한 번 활성화해야 하고, 최초 활성화 후 데이터가 보이기까지 최대 24시간이 걸린다.

**3-2. 메모리·디스크 에이전트 (CloudWatch Agent)**: 없으면 CPU만 수집된다.

```bash
sudo dnf install -y amazon-cloudwatch-agent
sudo cp scripts/agents/cloudwatch-agent-config.json /opt/aws/amazon-cloudwatch-agent/etc/config.json
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json -s
```

적용 후 첫 지표가 보이기까지 10~20분 걸릴 수 있다. 디스크 지표는 `device`/`fstype` 차원이 **정확히 일치**해야 조회된다:
`aws cloudwatch list-metrics --namespace CWAgent` 로 실제 값을 보고 다르면 `.env`의 `AWS_DISK_DEVICE`, `AWS_DISK_FSTYPE`를 맞춘다.

**3-3. 설정과 설치**

```bash
git clone https://github.com/acau7143/CloudFit.git && cd CloudFit
cp .env.example .env     # [공통] SERVER_URL, [AWS] AWS_REGION, AWS_INSTANCE_ID 를 채운다
bash scripts/install_collector.sh aws            # 점검 + cron 미리보기
bash scripts/install_collector.sh aws --apply    # 점검 통과 시 cron 등록
```

## 4. 수집 VM — GCP

**4-1. 권한 (VM에 연결된 서비스 계정)**: 개인 계정이 아니라 **VM이 실제로 쓰는 서비스 계정**에 부여한다.
확인: `curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email`

| 역할 | 용도 |
|---|---|
| `roles/monitoring.viewer` | CPU/메모리/디스크 지표 조회 |
| `roles/monitoring.metricWriter`, `roles/logging.logWriter` | Ops Agent가 지표·로그를 보냄 |
| `roles/compute.viewer` | 인스턴스·머신 사양, 미사용 디스크/IP 조회 |
| `roles/bigquery.dataViewer` (결제 내보내기 데이터셋), `roles/bigquery.jobUser` (프로젝트) | 비용 조회. 코드 호출 기준으로 정리한 후보이며 `check_prereqs`로 검증한다 |

VM의 API 액세스 범위가 제한돼 있으면 안 된다 (`cloud-platform` 범위 권장).

수집기는 `.env`의 `GCP_INSTANCE_NAME` VM의 지표만 조회한다. 프로젝트에 다른 VM이 있어도 그 VM의 값이 섞이지 않는다
(Monitoring 쿼리를 대상 VM의 숫자 id로 좁힌다).

**4-2. 메모리·디스크 에이전트 (Ops Agent)**

```bash
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
sudo bash add-google-cloud-ops-agent-repo.sh --also-install
sudo systemctl enable --now google-cloud-ops-agent
```

**4-3. 비용 수집용 결제 내보내기**: 콘솔 → 결제 → 결제 내보내기 → **BigQuery 내보내기 켜기**
(데이터셋 이름은 `billing_export`). **켠 시점부터만 쌓이고 과거 데이터는 채워지지 않는다.** 그동안은 수집기가 추정치로 대체한다.

**4-4. 설정과 설치**

```bash
git clone https://github.com/acau7143/CloudFit.git && cd CloudFit
cp .env.example .env   # [공통] SERVER_URL, [GCP] GCP_PROJECT_ID, GCP_ZONE, GCP_INSTANCE_NAME, GCP_BILLING_ACCOUNT_ID
bash scripts/install_collector.sh gcp
bash scripts/install_collector.sh gcp --apply
```

## 5. 수집 VM — Azure

> Azure cron 템플릿(`scripts/cron/collector-azure.cron`)은 Azure VM의 운영 crontab(2026-10-24 확인) 기준이다.
> 자원은 5분마다, 비용은 매일 09:00(UTC)에 `--costs`로 한 번만 수집한다. Cost Management API는 스코프당 분당 4회
> 제한이 있어(`incidents/INC-001`) 5분 줄에 `--costs`를 붙이면 안 된다. `--costs` 분리가 반영되지 않은 오래된 코드에서는
> 이 줄이 오류로 끝나니, 설치 전에 `git pull`로 최신 `main`을 받는다.

**5-1. 서비스 프린시펄과 권한** (상세: `azure-collector-setup-1~3.md`)

```bash
az ad sp create-for-rbac --name cloudfit-collector --role Reader \
  --scopes /subscriptions/<구독ID>/resourceGroups/<리소스그룹>
az role assignment create --assignee <appId> --role "Monitoring Reader" \
  --scope /subscriptions/<구독ID>/resourceGroups/<리소스그룹>
az role assignment create --assignee <appId> --role "Cost Management Reader" \
  --scope /subscriptions/<구독ID>/resourceGroups/<리소스그룹>
az role assignment create --assignee <appId> --role "Log Analytics Reader" \
  --scope <Log Analytics 작업 영역의 리소스 ID>
```

출력되는 `tenant`, `appId`, `password`가 각각 `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`이다. **`password`는 한 번만 보이므로 바로 `.env`에 옮긴다.**

**5-2. 메모리·디스크 에이전트**: Azure Monitor Agent + 데이터 수집 규칙(DCR) + Log Analytics 작업 영역 연결이 필요하다.
절차가 길어서 `azure-collector-setup-2.md`를 따른다. 작업 영역 ID가 `AZURE_LOG_WORKSPACE_ID`이다.

**5-3. 설정과 설치**

```bash
git clone https://github.com/acau7143/CloudFit.git && cd CloudFit
cp .env.example .env   # [공통] SERVER_URL, [Azure] 7개 키
bash scripts/install_collector.sh azure
```

## 6. 확인

수집 VM에서 5~10분 뒤:

```bash
tail -n 5 logs/<aws|gcp|azure>_resource.log
```

서버 VM에서:

```bash
curl -s "http://localhost:8000/resources?cloud=AWS" | head -c 600
```

대시보드에 CPU 패널이 채워지면 수집이 연결된 것이다. 아래는 **데이터가 쌓여야** 나오는 항목이라 설치 직후 비어 있는 것이 정상이다.

| 항목 | 필요한 데이터 |
|---|---|
| 이상탐지 | 최근 7일, 인스턴스당 20건 이상 (`ml/train.py`는 일요일 03:00에 학습) |
| 비용 예측 | 7일치 이상의 비용 기록 |
| 약정 전환 추천 | 위 데이터 + 서버 VM이 `allocation_rules`에 등록돼야 핵심 인프라로 취급됨 (`decisions/0013`) |

## 7. 점검 결과 읽는 법

`scripts/check_prereqs.py`(설치 스크립트가 자동 실행)는 항목별로 알려준다. 단독 실행: `.venv/bin/python scripts/check_prereqs.py <aws|gcp|azure|server>`

| 표시 | 뜻 |
|---|---|
| `[OK]` | 정상 |
| `[WARN]` | 동작은 하지만 그 데이터가 빈다 (에이전트 미설치, 비용 권한 등). 안내대로 조치 |
| `[FAIL]` | 수집이 안 된다. 해결 전에는 cron이 등록되지 않는다 |

## 8. 자주 막히는 곳

| 증상 | 원인과 조치 |
|---|---|
| cron이 돌지 않는데 오류도 안 보임 | `logs/` 폴더가 없으면 조용히 실패한다. 설치 스크립트가 만들지만 수동 설치했다면 `mkdir -p logs` |
| 실행 시각이 예상과 다름 | cron은 VM 시간대 기준이다. `timedatectl` 확인 |
| `ModuleNotFoundError` | cron 줄이 시스템 `python3`를 쓰는 경우. 설치 스크립트가 만든 `.venv/bin/python`을 쓰는지 `crontab -l`로 확인 |
| 수집기가 서버에 못 보냄 | 서버 VM 보안그룹의 8000 포트, `.env`의 `SERVER_URL` |
| 디스크 지표만 비어 있음 | AWS: `AWS_DISK_DEVICE`/`AWS_DISK_FSTYPE`, GCP: `GCP_DISK_DEVICE`(Ops Agent의 device 라벨) |
| GCP 메모리/디스크가 비어 있음 | Ops Agent 로그의 `API Check: FAIL` → 서비스 계정에 `metricWriter`/`logWriter` 추가 후 `sudo systemctl restart google-cloud-ops-agent` |
| Azure 비용 조회가 429 | 비용 API 호출 한도(스코프당 분당 4회). 비용은 `--costs`(하루 한 번)로만 호출하고 5분 줄에는 붙이지 않는다 (`incidents/INC-001`) |
| 스키마를 고쳤는데 DB에 반영 안 됨 | `db/schema.sql`은 DB 볼륨이 비어 있는 최초 기동에만 실행된다 (`server-setup.md` 4번) |

## 9. 되돌리기와 정리

- cron만 제거: `crontab -e`로 `# >>> cloudfit:... >>>` ~ `# <<< cloudfit:... <<<` 블록을 지운다. 또는 설치 때 출력된 백업으로 복원: `crontab ~/crontab.backup.<시각>`
- 새 계정에서 검증한 뒤에는 **VM, 디스크, 고정 IP, BigQuery 데이터셋, Log Analytics 작업 영역을 삭제**한다 (검증 환경도 비용이 발생한다).

## 10. 알려진 제한 (단계 3 이후)

- 서버 API에 인증이 없다 → 8000 포트를 반드시 수집 VM IP로만 연다. 외부에 공개하지 않는다.
- `docker-compose.yml`의 Grafana 관리자 비밀번호가 `admin`으로 고정돼 있다 (`.env`의 `GRAFANA_ADMIN_PASSWORD`는 아직 반영되지 않음). 첫 로그인 후 바로 바꾼다.
- DB 포트(5432)가 모든 인터페이스에 열려 있다 → 보안그룹에서 막는다.
- 클라우드당 수집 VM 1대 전제다.
- 비용 수집은 `--costs`(하루 한 번)에서만 한다. 이 분리가 없는 오래된 코드는 5분 실행도 비용을 보낸다.
