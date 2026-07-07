\# Azure VM Guest Metrics 수집 구성 Runbook



\## 1. 목적



Azure VM의 메모리 및 디스크 사용률을 수집하기 위해 Azure Monitor Agent(AMA), Data Collection Rule(DCR), Log Analytics Workspace(LAW)를 구성하고 Python 기반 Azure 수집기와 연동한다.



Azure VM의 CPU 사용률은 Azure Monitor의 기본 플랫폼 메트릭인 `Percentage CPU`를 통해 직접 조회할 수 있다.



반면 메모리와 디스크 사용률은 VM 내부 운영체제에서 측정되는 Guest OS 메트릭이므로, Azure Monitor Agent를 설치하고 수집 규칙을 설정해야 한다.



최종 수집 구조는 다음과 같다.



```text

CPU

Azure VM

&#x20; ↓

Azure Monitor Metrics API

&#x20; ↓

collectors/azure\_exporter.py





Memory / Disk

Azure VM

&#x20; ↓

Azure Monitor Agent (AMA)

&#x20; ↓

Data Collection Rule (DCR)

&#x20; ↓

Log Analytics Workspace (LAW)

&#x20; ↓

Perf table

&#x20; ↓

azure-monitor-query SDK

&#x20; ↓

collectors/azure\_exporter.py

```



\---



\## 2. 구성 요소



| 구성 요소 | 역할 |

|-----------|------|

| Azure Monitor Agent (AMA) | VM 내부의 메모리 및 디스크 성능 데이터를 실제로 수집한다. |

| Data Collection Rule (DCR) | 어떤 성능 카운터를 몇 초 간격으로 수집하고 어디로 전송할지 정의한다. |

| Log Analytics Workspace (LAW) | AMA가 수집한 데이터를 중앙에서 저장하고 KQL로 조회할 수 있도록 한다. |

| Perf table | 메모리 및 디스크 Performance Counter 데이터가 저장되는 테이블이다. |

| azure-monitor-query | Python 코드에서 Log Analytics Workspace에 KQL 쿼리를 실행하기 위한 SDK이다. |

| LogsQueryClient | Python에서 Workspace의 로그 데이터를 조회하는 클라이언트이다. |



간단히 정리하면 다음과 같다.



```text

AMA = 실제로 수집한다.

DCR = 무엇을 수집할지 지시한다.

LAW = 수집한 데이터를 저장하고 조회한다.

```



\---



\## 3. 사전 조건



다음 항목이 준비되어 있어야 한다.



\- Azure VM 생성 완료

\- Service Principal 생성 및 인증 확인 완료

\- `.env` 파일 구성 완료

\- Azure Monitor CPU 수집 확인 완료

\- Python Azure SDK 설치 완료

\- VM이 실행 중인 상태



현재 테스트 환경:



```text

Resource Group: rg-finops-test

VM: vm-finops-azure-test

Log Analytics Workspace: law-finops-test

Data Collection Rule: dcr-finops-azure-vm

Region: koreacentral

```



주의:



`.env`에는 Client Secret 등의 인증 정보가 포함되어 있으므로 GitHub에 업로드하지 않는다.



\---



\## 4. Azure Monitor Agent 설치



\### 4.1 VM 상태 확인



Azure Cloud Shell에서 실행한다.



```bash

az vm get-instance-view \\

&#x20; --resource-group rg-finops-test \\

&#x20; --name vm-finops-azure-test \\

&#x20; --query "instanceView.statuses\[?starts\_with(code, 'PowerState/')].displayStatus" \\

&#x20; -o tsv

```



정상 예시:



```text

VM running

```



\### 4.2 기존 Extension 확인



```bash

az vm extension list \\

&#x20; --resource-group rg-finops-test \\

&#x20; --vm-name vm-finops-azure-test \\

&#x20; -o table

```



\### 4.3 Azure Monitor Agent 설치



```bash

az vm extension set \\

&#x20; --resource-group rg-finops-test \\

&#x20; --vm-name vm-finops-azure-test \\

&#x20; --name AzureMonitorLinuxAgent \\

&#x20; --publisher Microsoft.Azure.Monitor \\

&#x20; --enable-auto-upgrade true

```



정상 설치 시 다음 항목을 확인한다.



```text

Name: AzureMonitorLinuxAgent

Publisher: Microsoft.Azure.Monitor

ProvisioningState: Succeeded

```



\---



\## 5. Log Analytics Workspace 생성



Azure Portal에서 Log Analytics Workspace를 생성한다.



설정 예시:



```text

Resource Group: rg-finops-test

Workspace Name: law-finops-test

Region: Korea Central

```



Workspace는 AMA가 수집한 VM 내부 성능 데이터를 저장하고 KQL로 조회하기 위한 공간이다.



하나의 Workspace에는 여러 VM의 데이터를 함께 저장할 수 있다.



\---



\## 6. Data Collection Rule 생성



Azure Portal에서 다음 경로로 이동한다.



```text

Azure Monitor

→ 설정

→ 데이터 수집 규칙

→ 만들기

```



DCR 설정 예시:



```text

Name: dcr-finops-azure-vm

Resource Group: rg-finops-test

Region: Korea Central

Telemetry Type: Agent-based - Linux

```



\### 6.1 Resource 연결



다음 VM을 DCR Resource로 연결한다.



```text

vm-finops-azure-test

```



하나의 DCR은 동일한 수집 정책을 적용할 여러 VM에 연결할 수 있다.



\### 6.2 Performance Counter 설정



수집 간격:



```text

300초

```



수집 대상:



```text

Memory(\*)\\Available MBytes Memory

Memory(\*)\\% Used Memory

Logical Disk(\*)\\% Free Space

Logical Disk(\*)\\% Used Space

```



Destination:



```text

Target Type: Log Analytics Workspace

Workspace: law-finops-test

```



\---



\## 7. Perf 테이블 데이터 확인



DCR 설정 후 데이터가 즉시 나타나지 않을 수 있으므로 잠시 기다린 후 확인한다.



Azure Portal에서 다음 경로로 이동한다.



```text

Log Analytics Workspace

→ law-finops-test

→ Logs

```



다음 KQL을 실행한다.



```kusto

Perf

| where TimeGenerated > ago(30m)

| order by TimeGenerated desc

| project TimeGenerated, Computer, ObjectName, CounterName, InstanceName, CounterValue

```



정상이라면 다음과 같은 데이터가 조회된다.



```text

ObjectName: Memory

CounterName: % Used Memory



ObjectName: Logical Disk

CounterName: % Used Space



ObjectName: Logical Disk

CounterName: % Free Space

```



메모리 및 디스크 값이 조회되면 다음 구간이 정상이라는 의미이다.



```text

VM

↓

AMA

↓

DCR

↓

LAW

↓

Perf table

```



\---



\## 8. Python SDK 설치



로컬 PowerShell에서 프로젝트 폴더로 이동한다.



```powershell

cd C:\\CloudFit

```



Log Analytics 조회용 SDK를 설치한다.



```powershell

py -m pip install azure-monitor-query

```



설치 확인:



```powershell

py -m pip show azure-monitor-query

```



설치 확인 당시 사용 버전:



```text

azure-monitor-query 2.0.0

```



\---



\## 9. Workspace ID 확인



Azure Cloud Shell에서 실행한다.



```bash

az monitor log-analytics workspace show \\

&#x20; --resource-group rg-finops-test \\

&#x20; --workspace-name law-finops-test \\

&#x20; --query customerId \\

&#x20; -o tsv

```



출력된 Workspace ID를 `.env`에 추가한다.



```env

AZURE\_LOG\_WORKSPACE\_ID=실제\_Workspace\_ID

```



`.env` 내부 변수의 작성 순서는 기능에 영향을 주지 않는다.



\---



\## 10. Python LAW 조회 검증



`azure\_exporter.py`에 바로 통합하기 전에 별도 검증 스크립트인 `azure\_log\_check.py`를 사용하여 Python에서 LAW 데이터를 조회할 수 있는지 먼저 확인한다.



실행:



```powershell

py azure\_log\_check.py

```



검증 대상:



```text

Memory / % Used Memory

Logical Disk / % Used Space

```



Linux VM은 여러 파일시스템을 가지므로 대표 디스크 사용률은 다음 조건의 값을 사용한다.



```text

CounterName = % Used Space

InstanceName = /

```



정상 출력 예시:



```json

{

&#x20; "cloud": "azure",

&#x20; "resource\_id": "vm-finops-azure-test",

&#x20; "resource\_type": "vm",

&#x20; "memory\_percent": 45.55,

&#x20; "disk\_percent": 10.7,

&#x20; "source": "actual"

}

```



\---



\## 11. 발생한 오류와 복구



\### 11.1 증상



`azure\_log\_check.py` 실행 중 다음 오류가 발생했다.



```text

AttributeError: 'str' object has no attribute 'name'

```



오류 발생 부분:



```python

columns = \[column.name for column in table.columns]

```



\### 11.2 원인



사용 중인 `azure-monitor-query 2.0.0`에서는 `table.columns`의 각 항목이 이미 문자열이다.



따라서 다음과 같은 접근이 발생한 것과 같다.



```python

"TimeGenerated".name

```



문자열에는 `name` 속성이 없으므로 오류가 발생했다.



\### 11.3 복구



기존 코드:



```python

columns = \[column.name for column in table.columns]

```



수정 코드:



```python

columns = list(table.columns)

```



수정 후 다음 항목의 조회에 성공했다.



```text

memory\_percent

disk\_percent

```



\---



\## 12. azure\_exporter.py 통합 구조



기존 `collectors/azure\_exporter.py`는 Azure Monitor Metrics API에서 CPU를 수집하고 있었다.



Day 05 작업에서 Log Analytics 조회 기능을 추가하여 다음 구조로 확장했다.



```text

collect\_resource\_metrics()

&#x20;       │

&#x20;       ├── MonitorManagementClient

&#x20;       │       └── Percentage CPU

&#x20;       │

&#x20;       └── LogsQueryClient

&#x20;               └── LAW Perf

&#x20;                    ├── % Used Memory

&#x20;                    └── % Used Space (/)

```



주요 함수 역할:



| 함수 | 역할 |

|------|------|

| `load\_config()` | `.env`에서 Azure 인증 정보와 Workspace ID를 읽는다. |

| `build\_credential()` | Service Principal 인증 객체를 생성한다. |

| `query\_cpu\_metric()` | Azure Monitor Metrics API에서 CPU 사용률을 조회한다. |

| `query\_guest\_metrics()` | LAW Perf 테이블에서 메모리 및 디스크 사용률을 조회한다. |

| `collect\_resource\_metrics()` | CPU, 메모리, 디스크 결과를 하나의 raw 데이터로 합친다. |

| `to\_common\_record()` | AWS 및 GCP와 비교 가능한 공통 JSON 형식으로 변환한다. |

| `run\_dry\_run()` | 중앙 서버나 DB에 저장하지 않고 현재 수집 결과를 출력한다. |



\---



\## 13. 통합 수집 검증



PowerShell에서 실행한다.



```powershell

py collectors\\azure\_exporter.py --dry-run

```



검증 당시 결과:



```json

{

&#x20; "cloud": "azure",

&#x20; "resource\_id": "vm-finops-azure-test",

&#x20; "resource\_type": "vm",

&#x20; "region": "koreacentral",

&#x20; "timestamp": "2026-07-07T07:55:00Z",

&#x20; "cpu\_percent": 0.52,

&#x20; "memory\_percent": 45.71,

&#x20; "disk\_percent": 10.74,

&#x20; "source": "actual"

}

```



확인 기준:



```text

cpu\_percent     → 숫자

memory\_percent  → 숫자

disk\_percent    → 숫자

```



세 값이 모두 숫자로 출력되면 통합 수집 성공으로 판단한다.



\---



\## 14. 장애 확인 기준



\### CPU가 null인 경우



확인할 항목:



\- VM 실행 상태

\- 최근 30분 이내 CPU 메트릭 존재 여부

\- Azure Monitor Metrics API 권한

\- Service Principal 인증 정보



\### memory\_percent가 null인 경우



확인할 항목:



\- AMA 설치 상태

\- DCR과 VM 연결 상태

\- `% Used Memory` Performance Counter 설정

\- LAW의 Perf 테이블 데이터 유입 여부



\### disk\_percent가 null인 경우



확인할 항목:



\- `% Used Space` Performance Counter 설정

\- `InstanceName="/"` 데이터 존재 여부

\- DCR Destination Workspace 설정

\- Perf 테이블 데이터 유입 여부



\---



\## 15. 검증 명령어 정리



\### AMA Extension 확인



```bash

az vm extension list \\

&#x20; --resource-group rg-finops-test \\

&#x20; --vm-name vm-finops-azure-test \\

&#x20; -o table

```



\### Python SDK 확인



```powershell

py -m pip show azure-monitor-query

```



\### Python LAW 조회 확인



```powershell

py azure\_log\_check.py

```



\### Azure Collector 통합 검증



```powershell

py collectors\\azure\_exporter.py --dry-run

```



\---



\## 16. Evidence



장애 발생 화면:



```text

evidence/day05-azure-log-query-fail.png

```



복구 후 LAW 조회 성공 화면:



```text

evidence/day05-azure-log-query-recovery-ok-1.png

evidence/day05-azure-log-query-recovery-ok-2.png

```



CPU, 메모리, 디스크 통합 수집 성공 화면:



```text

evidence/day05-azure-memory-collect-ok.png

```



\---



\## 17. 현재 완료 상태



```text

\[완료] Azure Monitor Agent 설치

\[완료] Log Analytics Workspace 생성

\[완료] Data Collection Rule 생성

\[완료] VM과 DCR 연결

\[완료] Memory Performance Counter 수집 확인

\[완료] Disk Performance Counter 수집 확인

\[완료] Perf 테이블 데이터 유입 확인

\[완료] Python LAW 조회 성공

\[완료] memory\_percent 추출 성공

\[완료] disk\_percent 추출 성공

\[완료] azure\_exporter.py 통합

\[완료] CPU + Memory + Disk --dry-run 검증

```

