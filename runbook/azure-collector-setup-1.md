\# Azure Collector Setup Runbook



\## 목적



Azure VM 자원 사용량을 Azure Monitor API로 수집하고, AWS/GCP 수집기와 맞출 수 있는 공통 JSON 형식으로 변환하는 절차를 정리한다.



현재 Day 04 범위에서는 CPU 사용률(`Percentage CPU`)만 수집한다.



메모리와 디스크 사용률은 Azure Monitor Agent 설정이 필요할 수 있으므로 이후 단계에서 확장한다.



\---



\## 대상 파일



```text

collectors/azure\_exporter.py

tests/test\_azure\_exporter.py

```



\---



\## 사전 준비



\### Azure 테스트 리소스



```text

리소스 그룹: rg-finops-test

VM 이름: vm-finops-azure-test

지역: koreacentral

OS: Ubuntu Server 24.04 LTS

```



\### Service Principal



Azure API를 사람 계정 로그인 없이 호출하기 위해 Service Principal을 사용한다.



필요 권한:



```text

Monitoring Reader

```



권한 범위:



```text

rg-finops-test 리소스 그룹

```



\---



\## 환경변수 설정



프로젝트 루트의 `.env` 파일에 아래 값을 설정한다.



```env

AZURE\_TENANT\_ID=비공개

AZURE\_CLIENT\_ID=비공개

AZURE\_CLIENT\_SECRET=비공개

AZURE\_SUBSCRIPTION\_ID=비공개

AZURE\_RESOURCE\_GROUP=rg-finops-test

AZURE\_VM\_NAME=vm-finops-azure-test

AZURE\_REGION=koreacentral

```



주의:



```text

.env 파일은 인증 정보가 들어 있으므로 GitHub에 올리면 안 된다.

.gitignore에 .env가 포함되어 있어야 한다.

```



\---



\## Python 패키지 설치



Windows PowerShell 기준:



```powershell

python -m pip install azure-identity azure-mgmt-monitor python-dotenv

```



`python` 명령이 제대로 동작하지 않으면 아래 명령을 사용한다.



```powershell

py -m pip install azure-identity azure-mgmt-monitor python-dotenv

```



\---



\## 실행 방법



프로젝트 루트에서 실행한다.



```powershell

python collectors\\azure\_exporter.py --dry-run

```



`python` 명령이 제대로 동작하지 않으면 아래처럼 실행한다.



```powershell

py collectors\\azure\_exporter.py --dry-run

```



\---



\## 정상 출력 예시



```json

{

&#x20; "cloud": "azure",

&#x20; "resource\_id": "vm-finops-azure-test",

&#x20; "resource\_type": "vm",

&#x20; "region": "koreacentral",

&#x20; "timestamp": "2026-07-03T12:39:00Z",

&#x20; "cpu\_percent": 0.24,

&#x20; "memory\_percent": null,

&#x20; "disk\_percent": null,

&#x20; "source": "actual"

}

```



\---



\## 출력 필드 의미



| 필드 | 의미 |

|------|------|

| cloud | 클라우드 제공자. Azure 수집기는 `azure` |

| resource\_id | 수집 대상 VM 이름 |

| resource\_type | 자원 유형. 현재는 `vm` |

| region | Azure 리전 |

| timestamp | Azure Monitor 메트릭 시간. UTC 기준 |

| cpu\_percent | VM 평균 CPU 사용률 |

| memory\_percent | 현재 미수집. 이후 Azure Monitor Agent 설정 후 확장 |

| disk\_percent | 현재 미수집. 이후 Azure Monitor Agent 설정 후 확장 |

| source | 실제 API 수집 데이터 여부. 현재는 `actual` |



\---



\## 단위 테스트 실행



`to\_common\_record()` 함수가 공통 형식으로 변환하는지 검증한다.



```powershell

py -m unittest -v tests.test\_azure\_exporter

```



정상 결과:



```text

test\_to\_common\_record (tests.test\_azure\_exporter.TestAzureExporter.test\_to\_common\_record) ... ok



\----------------------------------------------------------------------

Ran 1 test in 0.001s



OK

```



\---



\## 검증 기준



\### dry-run 성공 기준



```text

1\. JSON 형식으로 출력된다.

2\. cloud 값이 azure이다.

3\. resource\_id 값이 vm-finops-azure-test이다.

4\. cpu\_percent 값이 숫자 또는 null로 출력된다.

5\. memory\_percent, disk\_percent는 현재 null이다.

```



\### unit test 성공 기준



```text

Ran 1 test

OK

```



\---



\## 자주 발생하는 오류와 복구



\### 1. 환경변수 누락



증상:



```text

누락된 환경변수: ...

```



원인:



```text

.env 파일에 필요한 값이 없거나 파일 위치가 프로젝트 루트가 아닐 수 있다.

```



복구:



```text

.env 파일 위치와 변수명을 확인한다.

```



\---



\### 2. Azure 인증 실패



증상:



```text

\[ERROR] Azure 인증 실패

```



원인:



```text

AZURE\_TENANT\_ID, AZURE\_CLIENT\_ID, AZURE\_CLIENT\_SECRET 중 하나가 틀렸을 가능성이 있다.

```



복구:



```text

Service Principal 생성 시 발급받은 값을 다시 확인하고 .env를 수정한다.

```



\---



\### 3. Azure Monitor CPU 조회 실패



증상:



```text

Azure Monitor CPU 조회 실패

```



원인 후보:



```text

VM 이름 오류

리소스 그룹 이름 오류

권한 부족

Azure Monitor API 일시 오류

```



복구:



```text

.env의 AZURE\_RESOURCE\_GROUP, AZURE\_VM\_NAME 값을 확인한다.

Service Principal에 Monitoring Reader 권한이 있는지 확인한다.

잠시 후 다시 실행한다.

```



\---



\### 4. cpu\_percent가 null



증상:



```json

"cpu\_percent": null

```



원인 후보:



```text

VM이 꺼져 있음

최근 30분 안에 Azure Monitor 메트릭이 아직 없음

VM을 방금 켜서 메트릭 반영이 지연됨

```



복구:



```text

VM을 실행 상태로 만들고 5분 정도 기다린 뒤 다시 실행한다.

```



\---



\## Evidence



dry-run 성공 캡처:



```text

evidence/day04-azure-exporter-dry-run-ok.png

```



단위 테스트 성공 캡처:



```text

evidence/day04-azure-exporter-unit-test-ok.png

```



\---



\## 다음 확장 작업



```text

1\. Azure Monitor Agent 설정 후 메모리/디스크 메트릭 수집

2\. 여러 VM 반복 수집

3\. 서버 API로 수집 결과 전송

4\. 수집 주기 스케줄링

5\. 비용 데이터 수집 모듈과 연결

```

