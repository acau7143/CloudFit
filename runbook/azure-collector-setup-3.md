# Azure Collector Setup Runbook

## 1. 목적

Azure VM의 자원 사용량과 인스턴스 사양 정보를 수집하고, AWS/GCP 수집기와 비교 가능한 공통 JSON 형식으로 변환하는 절차를 정리한다.

현재 Azure 수집기는 다음 데이터를 수집한다.

- CPU 사용률
- 메모리 사용률
- 디스크 사용률
- VM 인스턴스 타입
- vCPU 수
- RAM 용량
- Resource Group 범위의 일별 비용
- 서비스별 비용 구분

자원 메트릭 레코드와 비용 레코드는 현재 별도 구조로 출력한다.

```text
RESOURCE METRICS
→ CPU / Memory / Disk / VM Spec

COST RECORDS
→ Date / Cost USD / Service / Granularity
```

자원 메트릭 레코드의 `cost_monthly`는 아직 직접 연결하지 않았으므로 현재 `null`을 유지한다. 실제 비용은 별도의 Cost Records에서 출력한다.

현재 수집 흐름은 다음과 같다.

```text
CPU
Azure VM
  ↓
Azure Monitor Metrics API
  ↓
query_cpu_metric()


Memory / Disk
Azure VM
  ↓
Azure Monitor Agent (AMA)
  ↓
Data Collection Rule (DCR)
  ↓
Log Analytics Workspace (LAW)
  ↓
Perf table
  ↓
LogsQueryClient
  ↓
query_guest_metrics()


VM Spec
Azure Compute API
  ↓
ComputeManagementClient
  ↓
query_vm_spec()
  ├── instance_type
  ├── vcpu
  └── ram_gb


Cost
Azure Cost Management
  ↓
CostManagementClient
  ↓
collect_cost()
  ↓
to_usd()
  ↓
to_common_cost_record()


자원 수집 결과
  ↓
collect_resource_metrics()
  ↓
to_common_record()

비용 수집 결과
  ↓
collect_cost()
  ↓
to_common_cost_record()

모든 결과
  ↓
--dry-run JSON 출력
```

---

## 2. 대상 파일

```text
collectors/azure_exporter.py
tests/test_azure_exporter.py
runbook/azure-collector-setup.md
```

실제 수집기는 다음 파일이다.

```text
collectors/azure_exporter.py
```

단위 테스트는 다음 파일에서 수행한다.

```text
tests/test_azure_exporter.py
```

---

## 3. 테스트 환경

```text
Resource Group: rg-finops-test
VM: vm-finops-azure-test
Region: koreacentral
OS: Ubuntu Server 24.04 LTS

Log Analytics Workspace:
law-finops-test

Data Collection Rule:
dcr-finops-azure-vm
```

현재 확인된 VM 사양:

```text
Instance Type: Standard_B2ats_v2
vCPU: 2
RAM: 1.0 GB
```

---

## 4. Service Principal 인증

Azure API를 사람 계정의 대화형 로그인 없이 호출하기 위해 Service Principal을 사용한다.

현재 테스트 환경의 역할과 범위:

```text
Monitoring Reader
→ rg-finops-test 리소스 그룹 범위
→ Azure Monitor 자원 메트릭 조회

Cost Management 판독기
→ Subscription 범위
→ Cost Management 비용 데이터 읽기
```

비용 조회는 읽기만 필요하므로 Cost Management 참가자가 아닌 판독기 역할을 사용한다.

Python에서는 다음 인증 객체를 사용한다.

```python
ClientSecretCredential
```

역할:

```text
.env의 Tenant ID
+ Client ID
+ Client Secret
        ↓
Azure API 호출에 사용할 인증 객체 생성
```

---

## 5. 환경변수 설정

프로젝트 루트의 `.env` 파일에 Azure 설정값을 저장한다.

```env
AZURE_TENANT_ID=비공개
AZURE_CLIENT_ID=비공개
AZURE_CLIENT_SECRET=비공개
AZURE_SUBSCRIPTION_ID=비공개

AZURE_RESOURCE_GROUP=rg-finops-test
AZURE_VM_NAME=vm-finops-azure-test
AZURE_REGION=koreacentral

AZURE_LOG_WORKSPACE_ID=비공개
```

주의:

```text
.env에는 인증 정보가 있으므로 GitHub에 업로드하지 않는다.
실제 인증값은 Runbook, Diary, Evidence에 기록하지 않는다.
```

`.gitignore`에 다음 항목이 포함되어 있어야 한다.

```gitignore
.env
__pycache__/
*.pyc
.venv/
venv/
```

---

## 6. Python 패키지 설치

로컬 PowerShell에서 프로젝트 폴더로 이동한다.

```powershell
cd C:\CloudFit
```

필요 패키지:

```powershell
py -m pip install azure-identity
py -m pip install azure-mgmt-monitor
py -m pip install azure-monitor-query
py -m pip install azure-mgmt-compute
py -m pip install azure-mgmt-costmanagement
py -m pip install python-dotenv
```

한 번에 설치하는 경우:

```powershell
py -m pip install azure-identity azure-mgmt-monitor azure-monitor-query azure-mgmt-compute azure-mgmt-costmanagement python-dotenv
```

설치 확인 예시:

```powershell
py -m pip show azure-monitor-query
```

```powershell
py -m pip show azure-mgmt-compute
```

```powershell
py -m pip show azure-mgmt-costmanagement
```

확인된 개발 환경 기준:

```text
azure-monitor-query: 2.0.0
azure-mgmt-compute: 38.1.0
azure-mgmt-costmanagement: 5.0.0
```

---

# 7. CPU 사용률 수집

## 7.1 수집 방식

CPU는 Azure의 기본 플랫폼 메트릭인 다음 값을 사용한다.

```text
Percentage CPU
```

수집 클라이언트:

```python
MonitorManagementClient
```

수집 함수:

```text
query_cpu_metric()
```

현재 수집 설정:

```text
Lookback: 최근 30분
Interval: PT5M
Aggregation: Average
```

흐름:

```text
Azure VM
  ↓
Azure Monitor Metrics API
  ↓
Percentage CPU
  ↓
cpu_percent
```

---

## 7.2 시간 범위 형식

Azure Monitor Metrics API의 시간 범위는 UTC 기준 ISO 8601 형태로 생성한다.

예:

```text
2026-07-02T10:30:18Z/2026-07-02T11:00:18Z
```

현재 코드는 UTC 시간 문자열을 다음 형식으로 만든다.

```text
YYYY-MM-DDTHH:MM:SSZ
```

---

# 8. 메모리 및 디스크 수집

## 8.1 수집 구조

메모리와 디스크 사용률은 Guest OS 내부 데이터이므로 다음 구조로 수집한다.

```text
Azure VM
  ↓
AMA
  ↓
DCR
  ↓
LAW
  ↓
Perf table
  ↓
LogsQueryClient
  ↓
azure_exporter.py
```

구성 요소 역할:

| 구성 요소 | 역할 |
|-----------|------|
| AMA | VM 내부의 성능 데이터를 실제로 수집한다. |
| DCR | 무엇을 몇 초 간격으로 수집하고 어디로 보낼지 정의한다. |
| LAW | 수집한 데이터를 저장하고 KQL로 조회할 수 있도록 한다. |
| Perf | Performance Counter 데이터가 저장되는 테이블이다. |
| LogsQueryClient | Python에서 LAW에 KQL 쿼리를 실행한다. |

간단히 정리하면:

```text
AMA = 수집
DCR = 규칙
LAW = 저장·조회
```

---

## 8.2 Azure Monitor Agent 설치

먼저 VM 상태를 확인한다.

Azure Cloud Shell:

```bash
az vm get-instance-view \
  --resource-group rg-finops-test \
  --name vm-finops-azure-test \
  --query "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus" \
  -o tsv
```

정상 예시:

```text
VM running
```

기존 Extension 확인:

```bash
az vm extension list \
  --resource-group rg-finops-test \
  --vm-name vm-finops-azure-test \
  -o table
```

AMA 설치:

```bash
az vm extension set \
  --resource-group rg-finops-test \
  --vm-name vm-finops-azure-test \
  --name AzureMonitorLinuxAgent \
  --publisher Microsoft.Azure.Monitor \
  --enable-auto-upgrade true
```

정상 상태 확인 기준:

```text
Name: AzureMonitorLinuxAgent
Publisher: Microsoft.Azure.Monitor
ProvisioningState: Succeeded
```

---

## 8.3 Log Analytics Workspace

사용한 Workspace:

```text
Resource Group: rg-finops-test
Workspace: law-finops-test
Region: Korea Central
```

Workspace는 여러 VM에서 수집한 로그와 성능 데이터를 중앙에서 저장하고 조회할 수 있다.

---

## 8.4 DCR 설정

Azure Portal 경로:

```text
Azure Monitor
→ 설정
→ 데이터 수집 규칙
```

사용한 DCR:

```text
Name: dcr-finops-azure-vm
Resource Group: rg-finops-test
Region: Korea Central
Telemetry Type: Agent-based - Linux
```

연결 대상:

```text
vm-finops-azure-test
```

수집 간격:

```text
300초
```

Performance Counter:

```text
Memory(*)\Available MBytes Memory
Memory(*)\% Used Memory
Logical Disk(*)\% Free Space
Logical Disk(*)\% Used Space
```

Destination:

```text
Target Type: Log Analytics Workspace
Workspace: law-finops-test
```

---

## 8.5 LAW 데이터 확인

Azure Portal 경로:

```text
Log Analytics Workspace
→ law-finops-test
→ Logs
```

KQL:

```kusto
Perf
| where TimeGenerated > ago(30m)
| order by TimeGenerated desc
| project TimeGenerated, Computer, ObjectName, CounterName, InstanceName, CounterValue
```

정상 수집 시 다음 데이터가 확인된다.

```text
Memory
→ % Used Memory

Logical Disk
→ % Used Space

Logical Disk
→ % Free Space
```

---

## 8.6 Workspace ID 확인

Azure Cloud Shell:

```bash
az monitor log-analytics workspace show \
  --resource-group rg-finops-test \
  --workspace-name law-finops-test \
  --query customerId \
  -o tsv
```

조회 결과를 `.env`에 저장한다.

```env
AZURE_LOG_WORKSPACE_ID=비공개
```

---

## 8.7 Python 메모리/디스크 조회 기준

수집 함수:

```text
query_guest_metrics()
```

메모리 사용률:

```text
CounterName = % Used Memory
```

대표 디스크 사용률:

```text
CounterName = % Used Space
InstanceName = /
```

Linux VM에는 여러 파일시스템이 존재하므로, 현재 프로젝트에서는 루트 파일시스템 `/`의 사용률을 대표 디스크 사용률로 사용한다.

예:

```text
/
/run
/dev
/boot/efi
```

여러 Instance 중 `/`만 선택한다.

---

# 9. VM 인스턴스 사양 수집

## 9.1 수집 목적

VM 사용률만으로는 과대 스펙 여부를 판단하기 어렵다.

따라서 다음 정보도 함께 수집한다.

```text
instance_type
vcpu
ram_gb
```

---

## 9.2 수집 방식

사용 클라이언트:

```python
ComputeManagementClient
```

수집 함수:

```text
query_vm_spec()
```

흐름:

```text
ComputeManagementClient
  ↓
virtual_machines.get()
  ↓
hardware_profile.vm_size
  ↓
VM Size 확인

resource_skus.list()
  ↓
현재 VM Size와 같은 SKU 찾기
  ↓
Capabilities 확인
  ├── vCPUs
  └── MemoryGB
```

---

## 9.3 현재 확인 결과

```text
instance_type: Standard_B2ats_v2
vcpu: 2
ram_gb: 1.0
```

현재 방식은 VM 사양을 코드 내부에 수동으로 매핑하지 않고 Azure Compute API에서 조회한다.

---

# 10. Azure Cost Management 비용 수집

## 10.1 수집 목적

Azure VM의 자원 사용률과 실제 비용을 함께 분석하여 비용 대비 활용률을 비교하고, 불필요한 자원이나 연결 리소스 비용을 식별하기 위해 비용 데이터를 수집한다.

Azure Monitor는 자원 메트릭을 제공하고, 비용 데이터는 Cost Management API에서 별도로 조회한다.

흐름:

```text
Azure Cost Management
        ↓
CostManagementClient
        ↓
collect_cost()
        ↓
Daily Cost 조회
        ↓
ServiceName + ResourceId 그룹화
        ↓
to_usd()
        ↓
to_common_cost_record()
        ↓
공통 비용 레코드
```

---

## 10.2 SDK 및 권한

필요 패키지:

```powershell
py -m pip install azure-mgmt-costmanagement
```

확인된 버전:

```text
azure-mgmt-costmanagement: 5.0.0
```

비용 조회 권한:

```text
대상: finops-collector
역할: Cost Management 판독기
범위: Subscription
```

---

## 10.3 조회 범위와 Query 기준

현재 비용 Query 설정:

```text
Scope: rg-finops-test Resource Group
Type: ActualCost
Timeframe: Custom
Lookback: 최근 7일
Granularity: Daily
Aggregation: Cost Sum
Grouping:
- ServiceName
- ResourceId
```

Resource Group 범위로 조회하여 테스트 프로젝트 관련 비용을 중심으로 분석한다.

---

## 10.4 최초 비용 API 호출 결과

최초 조회에서 확인한 기본 컬럼:

```text
Cost
UsageDate
Currency
```

결과 예시 형식:

```text
[비용, 20260707, 'KRW']
```

이 결과는 코드에 작성한 예시값이 아니라 Cost Management API가 실제 조회한 결과다.

---

## 10.5 서비스 및 리소스별 비용 분석

VM을 실행하지 않은 기간에도 비용이 조회되어 `ServiceName`과 `ResourceId` 기준으로 원인을 확인했다.

확인된 서비스 범주:

```text
Storage
Virtual Network
Virtual Machines
Bandwidth
Log Analytics
```

ResourceId 기준으로 확인한 관계:

```text
Storage
→ 테스트 VM의 OS Disk

Virtual Network
→ 테스트 VM 관련 Public IP

Virtual Machines
→ 테스트 VM 본체

Bandwidth
→ 테스트 VM 관련 네트워크 사용

Log Analytics
→ Log Analytics Workspace
```

확인 결과, VM Compute 비용이 0인 기간에도 OS Disk와 Public IP 관련 비용이 발생할 수 있음을 비용 데이터 기준으로 확인했다.

---

## 10.6 collect_cost()

수집 함수:

```text
collect_cost()
```

Azure API 원본 row는 다음 순서로 반환된다.

```text
[
    Cost,
    UsageDate,
    ServiceName,
    ResourceId,
    Currency
]
```

수집기에서는 `columns`와 `rows`를 결합해 Dictionary 형태로 변환한다.

```python
rows = [
    dict(zip(columns, row))
    for row in (result.rows or [])
]
```

변환 결과:

```text
{
    "Cost": ...,
    "UsageDate": ...,
    "ServiceName": ...,
    "ResourceId": ...,
    "Currency": ...
}
```

---

## 10.7 USD 변환

현재 프로젝트에서는 클라우드별 비용 단위를 통일하기 위해 USD로 변환한다.

개발 단계의 고정 환율:

```text
1 USD = 1350 KRW
```

지원 통화:

```text
KRW
USD
```

변환 함수:

```text
to_usd()
```

KRW 변환식:

```text
USD 비용 = KRW 비용 / 1350
```

예:

```text
1350 KRW
→ 1.0 USD
```

지원하지 않는 통화가 입력되면 임의 환율을 적용하지 않고 `ValueError`를 발생시킨다.

현재 고정 환율은 개발 및 변환 검증용이며, 추후 팀 합의나 환율 정책 변경 시 수정할 수 있다.

---

## 10.8 공통 비용 레코드

변환 함수:

```text
to_common_cost_record()
```

현재 출력 필드:

| 필드 | 의미 |
|------|------|
| `cloud` | 클라우드 제공자 |
| `date` | 비용 발생 날짜 |
| `cost_usd` | USD 변환 비용 |
| `currency` | 통일된 비용 통화 |
| `service` | Azure ServiceName |
| `granularity` | 비용 집계 단위 |

예:

```json
{
  "cloud": "azure",
  "date": "2026-07-07",
  "cost_usd": 0.119029,
  "currency": "USD",
  "service": "Storage",
  "granularity": "DAILY"
}
```

현재 공통 비용 레코드 형식은 팀 공통 비용 스키마 최종 합의 전의 임시 기준이다. 팀 미팅 후 변경 사항이 발생하면 차주 계획 시작 전에 `to_common_cost_record()`와 관련 테스트를 수정한다.

---

# 11. azure_exporter.py 구조

현재 주요 함수 역할:

| 함수 | 역할 |
|------|------|
| `load_config()` | `.env`에서 Azure 설정을 읽는다. |
| `build_credential()` | Service Principal 인증 객체를 만든다. |
| `build_resource_uri()` | 대상 VM의 Azure Resource URI를 만든다. |
| `make_timespan()` | CPU 메트릭 조회 시간 범위를 만든다. |
| `format_timestamp()` | Azure timestamp를 UTC 공통 형식으로 변환한다. |
| `query_cpu_metric()` | CPU 사용률을 조회한다. |
| `query_guest_metrics()` | LAW에서 메모리와 디스크 사용률을 조회한다. |
| `query_vm_spec()` | VM 타입, vCPU, RAM 정보를 조회한다. |
| `to_usd()` | 원본 비용을 USD 단위로 변환한다. |
| `to_common_cost_record()` | Azure 비용 데이터를 공통 비용 레코드로 변환한다. |
| `collect_cost()` | Resource Group 범위의 일별 비용을 조회한다. |
| `collect_resource_metrics()` | 여러 API의 자원 수집 결과를 하나의 raw 데이터로 합친다. |
| `to_common_record()` | 자원 데이터를 팀 공통 JSON 형식으로 변환한다. |
| `run_dry_run()` | 자원 메트릭과 비용 레코드를 서버 전송 없이 출력한다. |

전체 흐름:

```text
query_cpu_metric()
        │
        ├── cpu_percent
        │
query_guest_metrics()
        │
        ├── memory_percent
        └── disk_percent
        │
query_vm_spec()
        │
        ├── instance_type
        ├── vcpu
        └── ram_gb
        │
        ▼
collect_resource_metrics()
        │
        ▼
to_common_record()
        │
        └── RESOURCE METRICS

collect_cost()
        │
        ▼
to_common_cost_record()
        │
        ├── to_usd()
        └── COST RECORDS
```

---

# 12. 공통 출력 필드

## 12.1 자원 메트릭 레코드

| 필드 | 의미 |
|------|------|
| `cloud` | 클라우드 제공자 |
| `resource_id` | 대상 VM 이름 |
| `resource_type` | 자원 유형 |
| `region` | Azure Region |
| `timestamp` | CPU 메트릭 기준 UTC timestamp |
| `cpu_percent` | CPU 사용률 |
| `memory_percent` | 메모리 사용률 |
| `disk_percent` | 루트 파일시스템 사용률 |
| `instance_type` | Azure VM Size |
| `vcpu` | VM의 vCPU 수 |
| `ram_gb` | VM의 RAM 용량 |
| `cost_monthly` | 자원 레코드에는 아직 직접 연결하지 않아 현재 `null` |
| `source` | 실제 수집 데이터 여부 |

## 12.2 비용 레코드

| 필드 | 의미 |
|------|------|
| `cloud` | 클라우드 제공자 |
| `date` | 비용 발생 날짜 (`YYYY-MM-DD`) |
| `cost_usd` | USD로 변환한 비용 |
| `currency` | 공통 통화 단위 `USD` |
| `service` | Azure ServiceName |
| `granularity` | 비용 집계 단위 `DAILY` |

---

# 13. dry-run 실행

프로젝트 루트에서 실행한다.

```powershell
py collectors\azure_exporter.py --dry-run
```

현재 dry-run은 자원 메트릭과 비용 레코드를 함께 출력한다.

출력 구조:

```text
=== RESOURCE METRICS ===
자원 사용률 및 VM 사양

=== COST RECORDS ===
USD 변환된 일별·서비스별 비용
```

자원 레코드 예시:

```json
{
  "cloud": "azure",
  "resource_id": "vm-finops-azure-test",
  "resource_type": "vm",
  "region": "koreacentral",
  "timestamp": "2026-07-08T12:19:00Z",
  "cpu_percent": 0.443,
  "memory_percent": 45.04,
  "disk_percent": 10.8,
  "instance_type": "Standard_B2ats_v2",
  "vcpu": 2,
  "ram_gb": 1.0,
  "cost_monthly": null,
  "source": "actual"
}
```

비용 레코드 예시:

```json
{
  "cloud": "azure",
  "date": "2026-07-07",
  "cost_usd": 0.119029,
  "currency": "USD",
  "service": "Storage",
  "granularity": "DAILY"
}
```

실제 CPU, 메모리, 비용 값과 timestamp는 실행 시점 및 Cost Management 집계 상태에 따라 달라진다.

성공 기준:

```text
1. RESOURCE METRICS가 JSON 형식으로 출력된다.
2. CPU, Memory, Disk가 숫자 또는 정상적인 null 상태로 출력된다.
3. instance_type, vcpu, ram_gb가 출력된다.
4. COST RECORDS가 리스트 형태로 출력된다.
5. date가 YYYY-MM-DD 형식이다.
6. cost_usd가 숫자로 출력된다.
7. currency가 USD이다.
8. service가 Azure ServiceName 기준으로 출력된다.
9. granularity가 DAILY이다.
```

---

# 14. 단위 테스트

## 14.1 실행

PowerShell:

```powershell
py -m unittest -v tests.test_azure_exporter
```

현재 테스트 수:

```text
8개
```

자원 레코드 검증 항목:

```text
1. 전체 공통 필드가 정상 전달되는가?
2. Memory/Disk가 None이어도 정상 처리되는가?
3. 0.0 값을 None으로 잘못 처리하지 않는가?
4. Azure 내부 필드 metric_name이 공통 레코드에서 제거되는가?
```

비용 레코드 검증 항목:

```text
5. 1350 KRW가 1.0 USD로 변환되는가?
6. 이미 USD인 값이 동일하게 유지되는가?
7. 지원하지 않는 통화에 ValueError가 발생하는가?
8. Azure 비용 원본 데이터가 공통 비용 레코드로 정상 변환되는가?
```

정상 결과:

```text
Ran 8 tests

OK
```

---

# 15. stress-ng 부하 패턴 검증

## 15.1 목적

수집기가 실제 CPU 사용 패턴을 구분하여 수집할 수 있는지 확인하기 위해 낮은 부하, 중간 부하, 높은 부하 패턴을 생성한다.

이번 검증 패턴:

```text
10% → 저활용 패턴
55% → 정상 사용 패턴
90% → 과부하 패턴
```

---

## 15.2 SSH 접속

VM 공인 IP 확인 후 로컬 PowerShell에서 접속한다.

```powershell
ssh -i "개인키경로" azureuser@공인IP
```

실제 private key 경로와 공인 IP는 Runbook 및 Evidence에 기록하지 않는다.

SSH 종료:

```bash
exit
```

---

## 15.3 stress-ng 실행

### 저활용 패턴

```bash
stress-ng --cpu 0 --cpu-load 10 --timeout 600s
```

종료 후:

```text
5분 휴식
```

### 정상 패턴

```bash
stress-ng --cpu 0 --cpu-load 55 --timeout 600s
```

종료 후:

```text
5분 휴식
```

### 과부하 패턴

```bash
stress-ng --cpu 0 --cpu-load 90 --timeout 600s
```

종료 후:

```text
5분 휴식
```

전체 흐름:

```text
10% 부하 10분
→ 휴식 5분
→ 55% 부하 10분
→ 휴식 5분
→ 90% 부하 10분
→ 휴식 5분
```

총 약 45분의 패턴을 만든다.

---

## 15.4 Azure Monitor 그래프 확인

Azure Portal:

```text
VM
→ Monitoring
→ Metrics
```

설정:

```text
Metric: Percentage CPU
Aggregation: Average
Time Range: 최근 1시간 또는 최근 2시간
```

확인 기준:

```text
낮은 CPU 구간
→ 휴식
→ 중간 CPU 구간
→ 휴식
→ 높은 CPU 구간
```

목표값과 실제 그래프의 값이 정확히 10%, 55%, 90%로 일치할 필요는 없다.

다음과 같이 세 단계의 패턴이 명확하게 구분되는지를 확인한다.

```text
낮은 부하
중간 부하
높은 부하
```

---

## 15.5 stress 이후 Collector 재검증

SSH 세션 종료:

```bash
exit
```

로컬 PowerShell:

```powershell
py collectors\azure_exporter.py --dry-run
```

확인 항목:

```text
cpu_percent
memory_percent
disk_percent
instance_type
vcpu
ram_gb
```

stress-ng 테스트 이후에도 Collector가 정상 출력되면 검증 성공으로 판단한다.

---

# 16. 자주 발생하는 오류와 복구

## 16.1 환경변수 누락

증상:

```text
누락된 환경변수: ...
```

원인:

```text
.env 파일에 필요한 값이 없거나
프로젝트 루트에서 실행하지 않은 경우
```

복구:

```text
.env 위치 확인
환경변수 이름 확인
PowerShell 현재 경로 확인
```

---

## 16.2 Azure 인증 실패

증상:

```text
[ERROR] Azure 인증 실패
```

확인 항목:

```text
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
```

복구:

```text
Service Principal 정보와 .env 설정을 다시 확인한다.
비밀값은 출력하거나 캡처하지 않는다.
```

---

## 16.3 CPU Metrics API 시간 범위 오류

증상:

```text
BadRequest
Detected invalid time interval input
```

원인:

```text
timespan의 날짜 및 시간 문자열 형식이
Azure Monitor API 요구 형식과 일치하지 않음
```

복구:

```python
start_str = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
end_str = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

timespan = f"{start_str}/{end_str}"
```

---

## 16.4 cpu_percent가 null

원인 후보:

```text
VM이 꺼져 있음
VM을 방금 실행함
최근 조회 구간에 CPU 메트릭이 없음
Azure Monitor 반영 지연
```

복구:

```text
VM 상태 확인
5분 이상 기다린 후 다시 실행
최근 30분 데이터 존재 여부 확인
```

---

## 16.5 memory_percent가 null

확인 항목:

```text
AMA 설치 상태
DCR 연결 상태
% Used Memory Counter 설정
LAW Perf 데이터 유입 상태
Workspace ID
```

---

## 16.6 disk_percent가 null

확인 항목:

```text
% Used Space Counter 설정
InstanceName="/" 데이터 존재 여부
DCR Destination 설정
LAW Perf 데이터 유입 상태
```

---

## 16.7 LAW Python Query 오류

발생했던 오류:

```text
AttributeError: 'str' object has no attribute 'name'
```

문제 코드:

```python
columns = [column.name for column in table.columns]
```

원인:

```text
사용 중인 azure-monitor-query 2.0.0에서는
table.columns의 각 항목이 이미 문자열이었다.
```

복구:

```python
columns = list(table.columns)
```

수정 후 Python에서 Memory와 Disk 데이터 조회에 성공했다.

---

## 16.8 SSH private key 권한 오류

증상 예:

```text
WARNING: UNPROTECTED PRIVATE KEY FILE!
Permissions are too open.
Permission denied (publickey).
```

원인:

```text
Windows에서 private key 파일 권한이 너무 넓게 설정됨
```

복구 원칙:

```text
private key는 현재 사용자만 읽을 수 있도록 권한을 제한한다.
```

주의:

```text
private key 내용과 실제 경로는 Evidence와 GitHub에 노출하지 않는다.
```

---

## 16.9 VM 사양 조회 실패

증상 후보:

```text
VM Size 정보를 확인할 수 없습니다.
```

확인 항목:

```text
VM 이름
Resource Group
Compute API 권한
VM hardware_profile
Resource SKU 조회 결과
Region
```

`instance_type`은 확인되지만 `vcpu`, `ram_gb`가 `None`이면 현재 VM Size와 Resource SKU 조회 결과가 일치하는지 확인한다.

---

## 16.10 Cost Management 권한 부족

증상 예:

```text
401 Unauthorized
403 Forbidden
```

확인 항목:

```text
finops-collector에 Cost Management 판독기 역할이 있는지 확인
역할 범위가 Subscription인지 확인
역할 할당 직후라면 반영 시간을 두고 다시 실행
```

---

## 16.11 지원하지 않는 통화

증상 예:

```text
ValueError: 지원하지 않는 통화: ...
```

원인:

```text
EXCHANGE_RATE에 정의되지 않은 통화가 Cost Management 결과로 반환됨
```

복구:

```text
팀 환율 정책을 확인한 뒤 EXCHANGE_RATE를 명시적으로 확장한다.
알 수 없는 통화에 임의 환율 1.0을 적용하지 않는다.
```

---

# 17. 검증 명령어 모음

## VM 실행 상태

```bash
az vm get-instance-view \
  --resource-group rg-finops-test \
  --name vm-finops-azure-test \
  --query "instanceView.statuses[?starts_with(code, 'PowerState/')].displayStatus" \
  -o tsv
```

## AMA 확인

```bash
az vm extension list \
  --resource-group rg-finops-test \
  --vm-name vm-finops-azure-test \
  -o table
```

## Workspace ID 확인

```bash
az monitor log-analytics workspace show \
  --resource-group rg-finops-test \
  --workspace-name law-finops-test \
  --query customerId \
  -o tsv
```

## LAW Perf 확인

```kusto
Perf
| where TimeGenerated > ago(30m)
| order by TimeGenerated desc
| project TimeGenerated, Computer, ObjectName, CounterName, InstanceName, CounterValue
```

## Collector 검증

```powershell
py collectors\azure_exporter.py --dry-run
```

## 단위 테스트

```powershell
py -m unittest -v tests.test_azure_exporter
```

---

# 18. Evidence

## 기본 Azure Collector

```text
evidence/day04-azure-exporter-dry-run-ok.png
evidence/day04-azure-exporter-unit-test-ok.png
```

## Memory / Disk 수집

```text
evidence/day05-azure-log-query-fail.png
evidence/day05-azure-log-query-recovery-ok-1.png
evidence/day05-azure-log-query-recovery-ok-2.png
evidence/day05-azure-memory-collect-ok.png
```

## VM 사양 및 전체 필드 검증

```text
evidence/day06-azure-full-dry-run-ok.png
```

## 단위 테스트 및 부하 패턴 검증

```text
evidence/day07-azure-unit-tests-ok.png
evidence/day07-azure-stress-patterns.png
```

## 비용 수집 및 변환 검증

```text
evidence/day09-azure-cost-api-ok.png
evidence/day10-azure-cost-dry-run-ok.png
evidence/day12-azure-cost-unit-tests-ok.png
```

---

# 19. 현재 완료 상태

```text
[완료] Service Principal 인증
[완료] Azure Monitor CPU 수집
[완료] azure_exporter.py 기본 구조
[완료] --dry-run 출력
[완료] AMA 설치
[완료] LAW 생성
[완료] DCR 생성 및 VM 연결
[완료] Memory 수집
[완료] Disk 수집
[완료] Python LAW 조회
[완료] LAW 조회 오류 재현 및 복구
[완료] Azure Compute SDK 설치
[완료] VM Size 수집
[완료] vCPU 수집
[완료] RAM 용량 수집
[완료] CPU + Memory + Disk + VM Spec 통합
[완료] 공통 레코드 전체 필드 출력
[완료] 자원 메트릭 단위 테스트 4개 통과
[완료] stress-ng 10% 패턴 검증
[완료] stress-ng 55% 패턴 검증
[완료] stress-ng 90% 패턴 검증
[완료] Azure Monitor CPU 패턴 그래프 확인
[완료] stress 테스트 이후 Collector 재실행 검증
[완료] Cost Management 판독기 권한 설정
[완료] azure-mgmt-costmanagement 설치
[완료] Cost Management API 최초 호출
[완료] Resource Group 범위 비용 조회
[완료] ServiceName 기준 비용 그룹화
[완료] ResourceId 기준 비용 발생 리소스 확인
[완료] collect_cost() 구현
[완료] KRW → USD 변환 함수 구현
[완료] 공통 비용 레코드 변환 함수 구현
[완료] Resource Metrics + Cost Records 동시 dry-run
[완료] 비용 테스트 4개 추가
[완료] 전체 단위 테스트 8개 통과
```

---

# 20. 다음 확장 작업

```text
1. 팀 공통 비용 스키마 합의 결과 반영
2. to_common_cost_record() 최종 수정 및 관련 테스트 갱신
3. 고정 환율을 대체할 환율 정책 결정
4. 자원 메트릭과 비용 레코드의 연결 기준 설계
5. 여러 VM 반복 수집
6. 중앙 서버 API 전송
7. PostgreSQL 적재
8. 수집 주기 스케줄링
9. 비용 수집 예외 처리 및 재시도 범위 확장
10. 로그 기록 기능 추가
```
