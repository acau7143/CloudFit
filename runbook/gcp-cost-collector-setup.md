## 비용 수집 (Cloud Billing)

### 사전 준비
1. 서비스 계정에 `roles/billing.viewer` 권한 추가 — **개인(비조직) 결제 계정은 콘솔 UI에서 권한 관리 화면이 제한적으로 보일 수 있음. 이 경우 Cloud Shell에서 아래 명령어로 처리:**
```bash
   gcloud billing accounts add-iam-policy-binding {결제계정ID} \
     --member="serviceAccount:{서비스계정}" \
     --role="roles/billing.viewer"
```
2. BigQuery billing export 활성화: 결제 → 결제 내보내기 → 표준 사용량 비용 → 데이터셋(`billing_export`) 생성 후 저장
   - 데이터셋 생성 권한 없으면 `roles/bigquery.admin` 권한을 개인 계정에 추가 필요
   - 설정 후 실제 데이터가 쌓이기까지 최대 하루 소요 (당일에는 빈 결과가 정상)

### 주의: VM SSH ≠ Cloud Shell
VM에 SSH 접속해서 `gcloud` 명령어를 치면 **VM 서비스 계정**으로 자동 인증됨 (개인 계정 아님).
IAM 변경처럼 강한 권한이 필요한 작업은 반드시 **콘솔 우측 상단의 진짜 Cloud Shell**(`>_` 아이콘)에서 실행할 것.
- VM SSH 프롬프트: `user@finops-test:~$`
- Cloud Shell 프롬프트: `user@cloudshell:~ (project-id)$` ← 이 형태여야 개인 계정 인증

### 검증
```bash
python3 collectors/gcp_exporter.py --dry-run
```
출력 마지막 줄에 `{'cloud': 'GCP', 'date': ..., 'cost_usd': ..., ...}` 형태 레코드가 보이면 성공.
BigQuery 데이터 없을 시 `estimate_daily_cost()` 기반 추정값으로 자동 대체됨 (진짜 청구액 아님, 주의).