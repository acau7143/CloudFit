\# AWS 수집기 설치 및 실행 절차



\## 환경

\- 테스트 인스턴스: t3.micro, Amazon Linux 2023, ap-northeast-2 (서울)

\- 인스턴스 ID: i-05f7cdc5c5183e2ae

\- 참고: 팀 계획서는 Ubuntu 기준이지만 우리 인스턴스는 Amazon Linux로 진행함.

&#x20; 수집 코드는 boto3 API 호출만 하므로 대상 인스턴스 OS는 데이터/코드 병합에 영향 없음.

&#x20; (Agent 설치, stress-ng 설치 명령어만 dnf로 대체: apt → dnf)



\## 사전 준비

1\. IAM 사용자(finops-collector, ReadOnlyAccess) → 로컬 aws configure

2\. EC2 인스턴스에 별도 IAM 역할(CloudWatchAgentRole, CloudWatchAgentServerPolicy) 부착

&#x20;  ⚠️ 역할을 안 붙이면 Agent 로그에 `NoCredentialProviders` / `no EC2 instance role found` 에러 발생



\## CloudWatch Agent 설치 (메모리/디스크 수집용)

```bash

sudo dnf install -y amazon-cloudwatch-agent

```

config.json (메모리+디스크):

```json

{

&#x20; "metrics": {

&#x20;   "namespace": "CWAgent",

&#x20;   "append\_dimensions": { "InstanceId": "${aws:InstanceId}" },

&#x20;   "metrics\_collected": {

&#x20;     "mem":  { "measurement": \["mem\_used\_percent"] },

&#x20;     "disk": { "measurement": \["used\_percent"], "resources": \["/"] }

&#x20;   }

&#x20; }

}

```

적용 + 시작:

```bash

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \\

&#x20; -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/etc/config.json -s

```

상태 확인:

```bash

sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status

```



\## 메트릭 이름/차원 주의사항

\- CPU: `Namespace=AWS/EC2`, `MetricName=CPUUtilization`, Dimensions=\[InstanceId]

\- 메모리: `Namespace=CWAgent`, `MetricName=mem\_used\_percent`, Dimensions=\[InstanceId]

\- 디스크: `Namespace=CWAgent`, `MetricName=disk\_used\_percent`,

&#x20; Dimensions=\[InstanceId, path, device, fstype] \*\*4개 전부 정확히 일치해야 조회됨\*\*

&#x20; (실제 device/fstype 값은 `aws cloudwatch list-metrics --namespace CWAgent`로 확인)

\- ⚠️ 디스크 메트릭은 Agent 재시작 후 첫 반영까지 최대 10\~20분 지연될 수 있음

&#x20; (list-metrics 카탈로그엔 빨리 뜨지만 get-metric-statistics 조회엔 더 걸림)



\## Cost Explorer

\- 반드시 `region\_name="us-east-1"`로 호출 (인스턴스 리전과 무관)

\- 5분 주기 호출 금지 (호출당 $0.01, 데이터는 24시간마다 갱신)



## 비용 수집 (collect_cost / to_common_cost_record)

- 함수: `collect_cost(start_date=None, end_date=None)` — 기본 최근 7일 조회
- Cost Explorer 호출 시 `GroupBy=[{"Type":"DIMENSION","Key":"SERVICE"}]`로 **서비스별** 조회
  (decisions/0002: 특정 서비스 필터 없이 전 서비스 수집, 하루 총합 1행 아님)
- 각 그룹을 `to_common_cost_record(date, amount, unit, service)`로 공통 형식 변환
  → `{cloud:"AWS", date, cost_usd, currency:"USD", service, granularity:"DAILY"}`
- `UnblendedCost` 단위가 이미 USD라 환율 변환 불필요 (Azure 하드코딩 환율 / GCP 환율계산과의 차이점)
- 프리티어 계정은 대부분 서비스 비용이 `0 USD`로 나올 수 있음 (API 정상 동작, 실제 청구가 0)



\## stress-ng 부하 테스트

```bash

sudo dnf install -y stress-ng

stress-ng --cpu 1 --cpu-load 10 --timeout 300s   # 저활용

stress-ng --cpu 2 --cpu-load 55 --timeout 300s   # 정상

stress-ng --cpu 4 --cpu-load 90 --timeout 300s   # 과부하

```

검증: CloudWatch 콘솔 CPUUtilization 그래프에서 계단식 상승 확인



\## 검증 명령

```bash

python3 collectors/aws\_exporter.py --dry-run

python3 -m pytest tests/ -v

```

