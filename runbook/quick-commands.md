# 새 VM 명령어 치트시트

새 VM(Ubuntu 24.04)에서 서버와 수집기를 처음부터 올릴 때 칠 명령을 순서대로 모았다.
설명, 권한 목록, 문제 해결은 `new-environment-setup.md`를 본다.

- 세 클라우드(AWS·Azure·GCP) 모두 새 VM을 **Ubuntu 24.04**로 만들면 **서버 명령은 똑같다.**
- 수집기는 앞쪽(권한, 에이전트, `.env` 키)만 클라우드마다 다르고, 마지막 `install_collector.sh <클라우드>`는 같은 형태다.
- 각 단계는 앞 단계가 끝난 뒤에 한다. 아래 명령은 모두 **새 VM 안에서** 실행한다.

---

## 1. 서버 VM (AWS·Azure·GCP 공통)

**1-1. 선행 설치** — 끝나면 SSH를 닫았다가 다시 접속한다 (Docker 권한 적용)

```bash
sudo apt-get update && sudo apt-get install -y git docker.io docker-compose-v2 python3-venv curl
sudo usermod -aG docker $USER
```

**1-2. 저장소와 설정**

```bash
git clone https://github.com/acau7143/CloudFit.git && cd CloudFit
cp .env.example .env
```

DB와 Grafana 비밀번호를 랜덤으로 채운다 (두 줄을 한 번에).

```bash
P=$(openssl rand -hex 12)
sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$P|; s|^DATABASE_URL=.*|DATABASE_URL=postgresql://finops:$P@localhost:5432/finops_db|; s|^GRAFANA_ADMIN_PASSWORD=.*|GRAFANA_ADMIN_PASSWORD=$(openssl rand -hex 8)|" .env
```

**1-3. 설치와 점검** (10분 안팎. 끝에 `OK 3 / WARN 0 / FAIL 0`)

```bash
bash scripts/install_server.sh 2>&1 | tee ~/install_server.log
```

**1-4. cron 등록** (이미 수동으로 등록한 cron이 있는 VM에서는 하지 않는다)

```bash
bash scripts/install_server.sh --apply --skip-docker --skip-install
```

**1-5. 첫 학습** — 수집 데이터가 클라우드당 20건(약 2시간) 쌓인 뒤 한 번. 그 전에는 이상탐지가 "모델 파일이 아직 없습니다"라고 안내하고 건너뛴다.

```bash
.venv/bin/python ml/train.py
```

---

## 2. 수집 VM

수집 VM에는 Docker가 필요 없다. 선행 설치는 아래만 하고, 1-2의 `git clone`, `cp .env.example .env`를 똑같이 한다.

```bash
sudo apt-get update && sudo apt-get install -y git python3-venv curl
```

서버가 **다른 VM**이면 `.env`에서 `SERVER_URL` 줄의 `#`을 지우고 서버 주소로 바꾼다. **같은 VM**이면 비워 둔다.

| 단계 | GCP | AWS | Azure |
|---|---|---|---|
| ① 권한 | VM 서비스 계정 역할 6개 | EC2에 IAM 역할 연결 | 서비스 프린시펄 + 역할 4개 |
| ② 메모리·디스크 에이전트 | Ops Agent | CloudWatch Agent | Azure Monitor Agent + 수집 규칙(DCR) |
| ③ `.env` 키 | `GCP_*` 4개 | `AWS_*` 2개 | `AZURE_*` 7개 |
| ④ 설치 | `install_collector.sh gcp` | `install_collector.sh aws` | `install_collector.sh azure` |

①의 권한 목록과 만드는 방법은 `new-environment-setup.md`의 클라우드별 절(3·4·5번)에 있다.

### GCP

```bash
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh && sudo bash add-google-cloud-ops-agent-repo.sh --also-install
```

```bash
cat >> .env <<'EOF'
GCP_PROJECT_ID=<프로젝트 ID>
GCP_ZONE=asia-northeast3-a
GCP_INSTANCE_NAME=<이 VM 이름>
GCP_BILLING_ACCOUNT_ID=<청구 계정 ID>
EOF
```

```bash
bash scripts/install_collector.sh gcp            # 점검 + cron 미리보기
bash scripts/install_collector.sh gcp --apply    # 점검 통과 후 cron 등록
```

### AWS

```bash
wget https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb && sudo dpkg -i -E ./amazon-cloudwatch-agent.deb
```

```bash
sudo cp scripts/agents/cloudwatch-agent-config.json /opt/aws/amazon-cloudwatch-agent/etc/config.json
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json -s
```

```bash
cat >> .env <<'EOF'
AWS_REGION=ap-northeast-2
AWS_INSTANCE_ID=<이 EC2의 인스턴스 ID>
EOF
```

ARM(Graviton) 인스턴스면 위 주소의 `amd64`를 `arm64`로 바꾼다.

Ubuntu의 루트 파일시스템은 보통 `ext4`인데 디스크 지표의 기본값은 Amazon Linux용 `xfs`다. 점검에서 디스크 지표가 `[WARN]`이면
`.env`에 `AWS_DISK_FSTYPE=ext4`를 추가하고, 장치 이름은 `aws cloudwatch list-metrics --namespace CWAgent`로 확인해 `AWS_DISK_DEVICE`에 넣는다.

```bash
bash scripts/install_collector.sh aws            # 점검 + cron 미리보기
bash scripts/install_collector.sh aws --apply    # 점검 통과 후 cron 등록
```

### Azure

서비스 프린시펄 생성과 역할 부여는 `new-environment-setup.md` 5-1의 `az` 명령을, Azure Monitor Agent와 수집 규칙(DCR)은
`azure-collector-setup-2.md`를 따른다. 출력되는 `password`는 한 번만 보이므로 바로 `.env`에 옮긴다.

```bash
cat >> .env <<'EOF'
AZURE_TENANT_ID=<tenant>
AZURE_CLIENT_ID=<appId>
AZURE_CLIENT_SECRET=<password>
AZURE_SUBSCRIPTION_ID=<구독 ID>
AZURE_RESOURCE_GROUP=<리소스 그룹>
AZURE_VM_NAME=<이 VM 이름>
AZURE_LOG_WORKSPACE_ID=<작업 영역 ID>
EOF
```

```bash
bash scripts/install_collector.sh azure            # 점검 + cron 미리보기
bash scripts/install_collector.sh azure --apply    # 점검 통과 후 cron 등록
```

---

## 3. 확인과 정리

5~10분 뒤 수집 VM에서:

```bash
tail -n 5 logs/<gcp|aws|azure>_resource.log
```

서버 VM에서:

```bash
curl -s "http://localhost:8000/resources?cloud=<GCP|AWS|Azure>" | head -c 600
```

점검 스크립트만 따로 실행할 때:

```bash
.venv/bin/python scripts/check_prereqs.py <aws|gcp|azure|server>
```

cron을 되돌릴 때는 `crontab -e`로 `# >>> cloudfit:... >>>` ~ `# <<< cloudfit:... <<<` 블록을 지운다 (설치 때 백업: `~/crontab.backup.<시각>`).
테스트가 끝난 VM은 **VM, 디스크, 고정 IP를 삭제**한다 (요금이 계속 나간다).

> 이미 운영 중인 VM(crontab을 수동으로 등록한 VM)에서는 설치 스크립트 대신 점검만 쓴다 (`new-environment-setup.md` 8-1).

---

## 확인된 범위 (2026-10-24 기준)

| 항목 | 상태 |
|---|---|
| 서버 설치 1-1 ~ 1-5 | 새 GCP VM(Ubuntu 24.04, e2-medium)에서 실행해 확인 |
| 사전 점검 스크립트 | 운영 VM 3곳(AWS·GCP·Azure)에서 확인 |
| GCP 수집기 | 새 VM에서 확인 예정 (VM 서비스 계정 권한 대기) |
| AWS·Azure 수집기 | 새 VM에서는 아직 실행하지 않음. 이 문서의 AWS·Azure 명령은 운영 설정과 각 클라우드 공식 문서를 기준으로 작성 |
