# 새 VM 명령어 치트시트

새 VM(Ubuntu 24.04)에서 서버와 수집기를 처음부터 올릴 때 칠 명령을 순서대로 모았다.
설명, 권한 목록, 문제 해결은 `new-environment-setup.md`를 본다.

- 세 클라우드(AWS·Azure·GCP) 모두 새 VM을 **Ubuntu 24.04**로 만들면 **서버 명령은 똑같다.**
- 수집기는 앞쪽(권한, 에이전트, `.env` 키)만 클라우드마다 다르고, 마지막 `install_collector.sh <클라우드>`는 같은 형태다.
- 각 단계는 앞 단계가 끝난 뒤에 한다. 아래 명령은 모두 **새 VM 안에서** 실행한다.

---

## 0. VM 만들기 (GCP 예시)

이미 VM이 있으면 건너뛴다. 아래는 2026-10-24에 새 VM 검증에서 실제로 쓴 명령이다 (PowerShell이면 줄 끝의 `\`를 `` ` ``로 바꾼다).

```bash
gcloud compute instances create <VM 이름> \
  --zone=asia-northeast3-a --machine-type=e2-medium \
  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size=30GB --boot-disk-type=pd-balanced \
  --scopes=cloud-platform --labels=purpose=cleanroom-test
```

- `--scopes=cloud-platform`: 서비스 계정 권한이 API 범위에 막히지 않게 한다.
- 서비스 계정(`--service-account`)을 따로 주지 않으면 **기본 서비스 계정**이 붙는다. 그 계정에 `new-environment-setup.md` 4-1의 역할 6개가 있으면 GCP 수집기가 동작한다 (새 VM에서 확인).
- `Required 'iam.serviceAccounts.actAs' permission` 오류가 나면 **만드는 사람 계정**에 `서비스 계정 사용자`(`roles/iam.serviceAccountUser`) 역할이 없는 것이다. 프로젝트 소유자나 조직 관리자여도 자동으로 갖지 않는다.
- `--labels`는 나중에 지울 VM을 헷갈리지 않게 하려는 표시다.

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

Grafana는 자동으로 설정된다. `http://<서버>:3000`에 `admin` / `.env`의 `GRAFANA_ADMIN_PASSWORD`로 로그인하면 CloudFit 폴더에 대시보드가 있다.
(3000 포트는 본인 IP에만 연다. 이미 수동으로 Grafana를 설정해 둔 서버에서는 `bash scripts/install_server.sh --no-grafana-provision` — `new-environment-setup.md` 2번 참고)

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

서버 VM에서 **이미 `install_server.sh`로 패키지를 설치했다면** 수집기 등록은 `--apply --skip-install`로 해도 된다 (같은 `.venv`를 쓴다. 새 VM에서 이 방식으로 확인).

```bash
bash scripts/install_collector.sh gcp --apply --skip-install
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

**바로 확인하려면** (cron을 기다리지 않고 한 번 실행. 서버로 실제 전송한다):

```bash
.venv/bin/python collectors/<gcp|aws|azure>_exporter.py           # 자원만 전송
.venv/bin/python collectors/<gcp|aws|azure>_exporter.py --costs   # 자원 + 비용 전송
```

보내지 않고 값만 보려면 `--dry-run`을 붙인다.

cron이 스스로 도는지는 **다음 5분 지점(:00, :05, :10…)이 지난 뒤** 수집 VM에서 본다.
등록 직후에는 `logs/`가 비어 있는 것이 정상이다 (수동 실행 출력은 이 로그에 남지 않는다).

```bash
tail -n 5 logs/<gcp|aws|azure>_resource.log
```

`[OK] 자원 데이터 저장 성공: ...` 줄이 있고 비용 줄이 없으면 정상이다.
GCP 로그에 `httplib2 transport does not support per-request timeout` 경고가 반복돼도 구글 API 라이브러리가 내는 메시지일 뿐 저장에는 영향이 없다.

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

GCP 테스트 VM 삭제 예시 — **지우기 전에 라벨부터 확인**해서 운영 VM을 지우지 않게 한다.

```bash
gcloud compute instances list --format="table(name,zone.basename(),status,labels)"
```

```bash
gcloud compute instances delete <테스트 VM 이름> --zone=asia-northeast3-a
```

기본 설정이면 부팅 디스크는 VM과 함께 지워진다. 지운 뒤 `gcloud compute disks list`, `gcloud compute addresses list`로 남은 디스크·고정 IP가 없는지 본다.

> 이미 운영 중인 VM(crontab을 수동으로 등록한 VM)에서는 설치 스크립트 대신 점검만 쓴다 (`new-environment-setup.md` 8-1).

---

## 확인된 범위 (2026-10-24 기준)

| 항목 | 상태 |
|---|---|
| 서버 설치 1-1 ~ 1-5 | 새 GCP VM(Ubuntu 24.04, e2-medium)에서 실행해 확인 |
| 사전 점검 스크립트 | 운영 VM 3곳(AWS·GCP·Azure)에서 확인 |
| GCP 수집기 | 새 GCP VM(기본 서비스 계정, 역할 6개)에서 실행해 확인: 사전 점검 OK 8 / WARN 0 / FAIL 0, cron 등록, 수동 실행 시 자원만 저장(`--costs`를 주면 비용까지 저장), 서버 DB에 이 VM의 instance id로 저장됨, cron의 첫 5분 주기가 스스로 실행되어 로그에 저장 성공이 남음 |
| Grafana 자동 설정 | 새 GCP VM(Grafana 13.1.8)에서 설치 스크립트로 확인: `.env` 비밀번호로 로그인(`admin`/`admin`은 거부), 데이터소스 연결 정상, CloudFit 폴더에 대시보드 자동 등록, 테스트 데이터로 패널 8개가 모두 그려짐(화면 캡처로 확인). 재실행해도 정상. **이미 수동 설정된 Grafana에 같은 uid·다른 이름의 데이터소스가 있으면 시작 실패**를 재현해 별도 파일로 분리함 |
| 서버 cron 등록 (1-4) | 같은 VM에서 서버 cron과 수집기 cron이 한 crontab에 함께 등록됨(블록 2개) |
| AWS·Azure 수집기 | 새 VM에서는 아직 실행하지 않음. 이 문서의 AWS·Azure 명령은 운영 설정과 각 클라우드 공식 문서를 기준으로 작성 |
