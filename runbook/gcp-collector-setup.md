# GCP Collector 설치 및 실행 절차

> 담당: C (GCP)
> 최종 업데이트: 2026-07-05 (Day 03)
> 이 문서는 누적 참고 문서입니다. 작업할 때마다 내용을 업데이트하세요.

## 개요

GCP Compute Engine 인스턴스의 CPU / 메모리 / 디스크 사용률과 인스턴스 사양(vCPU, RAM)을 수집해서, 프로젝트 공통 포맷(`cloud`, `instance_id`, `timestamp`, `cpu_avg`, `memory_avg`, `disk_avg`, `instance_type`, `vcpu`, `ram_gb`, `cost_monthly`)으로 변환하는 수집기(`collectors/gcp_exporter.py`)를 설치하고 실행하는 절차입니다.

---

## 1. 사전 준비

- GCP 프로젝트 및 테스트용 인스턴스(예: e2-micro) 생성
- 인스턴스 안에서 Python 가상환경(venv) 생성 후 활성화

```bash
python3 -m venv finops-env
source finops-env/bin/activate
```

- 필요한 패키지 설치

```bash
pip install google-cloud-monitoring google-cloud-billing google-api-python-client pytest
```

**주의:** `google-cloud-monitoring`(Cloud Monitoring 전용 클라이언트)과 `google-api-python-client`(`discovery.build`, Compute Engine 등 범용 클라이언트)는 서로 다른 라이브러리 계열입니다. 하나만 설치하면 안 됩니다.

---

## 2. IAM 권한 (VM 서비스 계정 기준)

**핵심 원칙: 권한은 반드시 "VM에 실제로 연결된 서비스 계정"에 부여해야 합니다. 콘솔에 로그인한 개인 계정(Google 계정)에 권한을 줘도 VM 안의 코드/에이전트에는 아무 효과가 없습니다.**

VM이 실제로 쓰는 서비스 계정 확인:

```bash
curl -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email
```

필요한 역할:

| 역할 | 용도 |
|------|------|
| `roles/monitoring.viewer` | CPU/메모리/디스크 메트릭 조회 (`collect_cpu`, `collect_memory`, `collect_disk`) |
| `roles/monitoring.metricWriter` | Ops Agent가 메모리/디스크 메트릭을 Cloud Monitoring에 전송 |
| `roles/logging.logWriter` | Ops Agent가 로그를 Cloud Logging에 전송 |
| `roles/compute.viewer` | 인스턴스 사양 조회 (`get_instance_spec`, `compute.instances.get`) |

IAM 콘솔에서 추가: **IAM 및 관리자 → IAM → 해당 서비스 계정 → 연필 아이콘 → 다른 역할 추가**

---

## 3. Ops Agent 설치 (메모리/디스크 수집 필수)

기본 Cloud Monitoring은 CPU만 제공합니다. 메모리/디스크는 Ops Agent 설치가 필요합니다.

```bash
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
sudo bash add-google-cloud-ops-agent-repo.sh --also-install
sudo systemctl start google-cloud-ops-agent
sudo systemctl enable google-cloud-ops-agent
```

**검증:**

```bash
sudo systemctl status google-cloud-ops-agent
```

`API Check` 항목이 `PASS`로 나와야 정상입니다.

**실패 시 증상:** `API Check: FAIL, Error code: MonApiPermissionErr / LogApiPermissionErr` → 2번 IAM 권한(`monitoring.metricWriter`, `logging.logWriter`)이 VM 서비스 계정에 없는 경우입니다. 권한 추가 후 재시작:

```bash
sudo systemctl restart google-cloud-ops-agent
```

---

## 4. 메트릭 필터 주의사항 (라벨 필터링 필수)

GCP의 메모리/디스크 메트릭은 하나의 리소스를 여러 **상태(state) 라벨**로 쪼개서 제공합니다. 필터링 없이 조회하면 여러 상태 값이 한꺼번에 섞여서 나옵니다.

### CPU

```
metric.type="compute.googleapis.com/instance/cpu/utilization"
```

- 원본 값이 0~1 사이(예: `0.14` = 14%)라서 `* 100` 변환이 필요합니다.
- **변환은 `collect_cpu()` 내부에서 한 번만 처리합니다.** `to_common_record()`에서 다시 곱하면 이중 변환(예: 1400%)이 발생합니다.

### 메모리

```
metric.type="agent.googleapis.com/memory/percent_used" AND metric.label.state="used"
```

- `state` 라벨 값: `free`, `used`, `buffered`, `cached`, `slab_reclaimable` (5가지, 합이 100%)
- `state` 필터 없이 조회하면 5가지 상태가 섞여서 나옵니다 (예: 10분 동안 9개 시점 × 5개 상태 = 45개 값).

### 디스크

```
metric.type="agent.googleapis.com/disk/percent_used" AND metric.label.device="/dev/sda1" AND metric.label.state="used"
```

- `device` 라벨: 파티션별로 별도 시계열이 나옵니다. 이 프로젝트의 테스트 인스턴스는 `/dev/sda1`(루트, `/`)과 `/dev/sda15`(EFI 부팅 파티션, `/boot/efi`) 2개가 있습니다. **`/dev/sda1`만 사용합니다** — 실제 데이터/부하가 쌓이는 파티션이라 저활용/부족 판단에 의미가 있고, `sda15`는 크기가 작은(약 124M) 부팅 전용 파티션이라 무관합니다.
- `device` 이름은 머신 타입/이미지에 따라 달라질 수 있습니다 (예: `/dev/nvme0n1p1`). 다른 인스턴스에 적용할 때는 아래 검증 스크립트로 먼저 라벨을 확인하세요.

**라벨 확인용 정찰 코드** (새 인스턴스에 적용하기 전 먼저 실행):

```python
for result in results:
    print("라벨:", dict(result.metric.labels))
```

**검증:** `df -h`, `free -h` 실행 결과와 API 값을 대조합니다. 완전히 똑같을 필요는 없고, 같은 범위대(예: 30%대 vs 30%대)면 정상입니다.

---

## 5. 인스턴스 사양 조회

```python
from googleapiclient import discovery

compute = discovery.build('compute', 'v1')
instance = compute.instances().get(
    project=project_id,
    zone=zone,
    instance=instance_name
).execute()

machine_type = instance['machineType'].split('/')[-1]  # 예: e2-micro
```

- `MACHINE_SPECS` 매핑 테이블에 없는 머신 타입이 들어오면 `vcpu`, `ram_gb`는 `None`으로 채워지고 프로그램은 죽지 않습니다. 새 머신 타입을 쓸 경우 테이블에 직접 추가해야 정확한 값이 들어갑니다.

```python
MACHINE_SPECS = {
    'e2-micro':  {'vcpu': 2, 'ram_gb': 1},
    'e2-small':  {'vcpu': 2, 'ram_gb': 2},
    'e2-medium': {'vcpu': 2, 'ram_gb': 4},
}
```

**실패 시 증상:** `403 Forbidden ... Required 'compute.instances.get' permission` → 2번의 `roles/compute.viewer` 권한이 없는 경우입니다.

---

## 6. 실행 (--dry-run)

```bash
cd ~/CloudFit
python3 collectors/gcp_exporter.py --dry-run
```

**정상 출력 예시:**

```
{'cloud': 'GCP', 'instance_id': '5207434110382276471', 'timestamp': '2026-07-05T02:38:09.077822+00:00', 'cpu_avg': 13.97, 'memory_avg': 39.06, 'disk_avg': 39.18, 'instance_type': 'e2-micro', 'vcpu': 2, 'ram_gb': 1, 'cost_monthly': None}
```

---

## 7. 단위 테스트

```bash
pytest tests/test_gcp_exporter.py -v
```

테스트는 실제 GCP API를 호출하지 않습니다 (`to_common_record()`는 가짜 리스트를 입력받아 계산 로직만 검증). 확인 항목:
- `cloud` 필드가 `"GCP"`로 정확히 들어가는지
- CPU/메모리/디스크 평균 계산이 정확한지
- `MACHINE_SPECS`에 없는 머신 타입이 들어와도 안 죽는지 (`vcpu`/`ram_gb` → `None`)
- 빈 리스트가 들어와도 안 죽는지 (`cpu_avg` → `None`)

---

## 8. stress-ng로 부하 패턴 검증 (선택)

```bash
sudo apt install -y stress-ng

nohup bash -c 'stress-ng --cpu 1 --cpu-load 10 --timeout 600s && stress-ng --cpu 1 --cpu-load 55 --timeout 600s && stress-ng --cpu 1 --cpu-load 90 --timeout 600s' > stress.log 2>&1 &
```

**검증 방법:** GCP 콘솔 → Compute Engine → 인스턴스 → **관측 가능성 탭 → CPU** → 시간 범위를 실행 시각(`stat stress.log`의 `Birth`~`Modify` 시간) 기준으로 좁혀서 확인.

**참고:** `--cpu-load` 기본 방식(`all`)은 목표 %를 정확히 유지하지 못해 그래프가 계단이 아니라 스파이크로 보일 수 있습니다. 이럴 때는 "프로세스 CPU 그룹" 패널에서 `stress-ng-cpu` 프로세스의 PID와 `stress.log`에 기록된 PID를 대조하면 각 단계가 순서대로 실행됐는지 확인할 수 있습니다.

---

## 트러블슈팅 모음

| 증상 | 원인 | 해결 |
|------|------|------|
| Ops Agent `API Check: FAIL` | VM 서비스 계정에 `metricWriter`/`logWriter` 권한 없음 | IAM에서 역할 추가 후 `systemctl restart google-cloud-ops-agent` |
| IAM 역할을 줬는데도 효과 없음 | 개인 계정(Google 로그인 계정)에 줬음, VM 서비스 계정이 아님 | 메타데이터 서버로 실제 서비스 계정 이메일 확인 후 그 계정에 재부여 |
| `ModuleNotFoundError: No module named 'google'` | venv 활성화 안 함 | `source finops-env/bin/activate` 확인 (`(finops-env)` 표시 확인) |
| `ModuleNotFoundError: No module named 'googleapiclient'` | `google-api-python-client` 미설치 | `pip install google-api-python-client` |
| `403 Forbidden ... compute.instances.get` | `roles/compute.viewer` 권한 없음 | IAM에서 역할 추가 |
| 메모리/디스크 값이 여러 개로 뒤섞여 나옴 (예: 45개) | `state` 라벨 필터 누락 | 필터에 `AND metric.label.state="used"` 추가 |
| CPU 값이 비정상적으로 큼 (예: 1400%) | `collect_cpu()`와 `to_common_record()`에서 `* 100`을 이중으로 적용 | 변환은 `collect_cpu()` 내부에서만 1회 수행 |
| pytest가 실제 GCP를 호출하는 줄 알았음 | `if __name__ == "__main__":` 블록은 import 시 실행 안 됨 (파이썬 기본 동작) | 정상 동작, 걱정할 필요 없음 |

---

## 다음 개선 사항 (TODO)

- `PROJECT_ID`가 코드에 하드코딩되어 있음 → 환경변수(`os.environ`)로 전환 권장
- `MACHINE_SPECS`에 없는 머신 타입 쓸 경우 테이블에 직접 추가 필요
- `stress-ng --cpu-method` 기본값(`all`) 대신 특정 방식을 지정하면 더 안정적인 그래프 확인 가능 (예: `--cpu-method matrixprod`)