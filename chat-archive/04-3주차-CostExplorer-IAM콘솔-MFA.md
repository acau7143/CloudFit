# 대화 백업 — 3주차 Cost Explorer · IAM 콘솔 로그인 · MFA

> 원본 세션: "Week 3 AWS cost collection plan"
> 내용: 2주차 마무리 확인 → placeholder 폴더 정리 → IAM 콘솔 로그인/MFA 문제 해결 → 서브계정 논의 → 3주차 Cost Explorer 계획 시작 → EC2 SSH/실행 위치 혼동 정리

---

## 1. placeholder 폴더 정리 (2주차 세션 연속)
`aws/`(test_cpu.py만 남음), `azure/`, `gcp/`, `docs/` 전부 비어있음 → `git rm -r aws/ azure/ gcp/ docs/` → 커밋 `chore: 1주차 초기 placeholder 폴더 정리`. 실제 코드는 collectors/, runbook/로 이미 통합. 브랜치 각각 따로라 내 브랜치엔 aws만 있으면 됨.

## 2. IAM 콘솔 로그인 문제
`finops-collector`는 콘솔 로그인 권한을 애초에 안 줌(코드 전용 출입증). 어느 기기에서도 그 계정으론 콘솔 로그인 불가가 정상. 이 노트북에서 됐던 건 루트 계정 자동완성 때문.
→ **개인용 IAM 사용자 `wjh61734`** 신규 생성 (콘솔 액세스 + Custom password + AdministratorAccess). **같은 AWS 계정 안 출입증 추가**지 새 계정/새 카드 아님.

## 3. MFA를 휴대폰 인증앱으로
이전엔 패스키(Windows Hello)로 등록 → 그 노트북에서만 작동(설계상 정상).
→ 다른 기기에서도 로그인하려면 **휴대폰 인증앱(Google/Microsoft Authenticator) MFA** 추가.
- IAM > 사용자 > wjh61734 > 보안 자격 증명 > MFA 디바이스 할당 > **"인증 관리자 앱"** 선택(패스키 아님).
- QR 아래 "키 표시(Show secret key)" 문자열도 메모(다른 기기 추가 시 재사용).
- 디바이스 이름은 영문/숫자만(한글·공백 불가): 예 `wjh-phone`.
- 코드 2개 연속 입력하면 할당 완료. 이제 어느 브라우저에서든 로그인 가능.
- 로그인 시: "Account ID or alias" 칸에 `379057358736`, IAM username에 `wjh61734`.

## 4. 서브계정(다른 프로젝트용) 논의
계정 하나뿐이라 프로젝트 구분 필요. 두 방법:
- 네이밍 + 태그 규칙: `finops-*` vs `{다른}-*`, 리소스에 `Project:` 태그. Cost Explorer에서 태그별 비용 조회.
- **AWS Organizations**: 새 카드 없이 완전 분리된 서브 계정 추가 가능(결제만 메인 통합). 나중에 PC에서 진행하기로 함.

## 5. 3주차 Cost Explorer 계획 (팀장 플랜)
- **Day 1**: Cost Explorer 활성화 (Billing & Cost Management > Cost Explorer > Enable, 데이터 최대 24h 지연) + IAM 권한 `AWSCostExplorerReadOnlyAccess` 추가 + 첫 API 호출.
  - `ce = boto3.client('ce', region_name='us-east-1')` (Cost Explorer는 us-east-1 고정)
  - `get_cost_and_usage`로 EC2 일별 비용 조회, `0.0123 USD` 형태 출력되면 성공.
- **Day 2**: `collect_cost()` 함수 + `to_common_cost_record()` 변환 함수. aws_exporter.py에 통합.
  - 공통 비용 형식: `{cloud:"AWS", date, cost_usd:float, currency:"USD", service:"EC2", granularity:"DAILY"}`
- **Day 4**: 단위 테스트 + DB 스키마 cost_records 반영 + runbook 비용 섹션 추가.

**진행 상황**: Cost Explorer 활성화 완료, IAM 권한 추가 진행.

## 6. EC2 SSH / 파이썬 실행 위치 혼동 정리 (중요)
- `aws_exporter.py`는 `~/CloudFit/collectors/`에 있음. AWS 콘솔에서 여는 게 아니라 로컬 에디터로 편집.
- 이 스크립트는 boto3로 AWS API를 **원격 호출**만 함 → **로컬(본인 컴퓨터)**에서 실행. EC2 안에서 실행 아님.
- EC2 안에서 실행하면 두 문제: (1) boto3 미설치(`pip3 install boto3 --user`, pip 없으면 `sudo dnf install -y python3-pip` 먼저) (2) 인스턴스 역할(CloudWatchAgentRole)엔 push 권한만 있고 read 권한 없어 `AccessDenied`.
  - EC2에서 굳이 실행하려면 역할에 `CloudWatchReadOnlyAccess` + `AmazonEC2ReadOnlyAccess` 추가 필요.
- 로컬엔 이미 finops-collector(ReadOnlyAccess)로 aws configure 돼 있어서 로컬 실행이 바로 됨.
- MobaXterm으로 SSH 접속해서 실행 중이었음.

## 7. SSH 접속 트러블슈팅 기록
- SSH는 인스턴스를 "켜는" 게 아니라 이미 running인 인스턴스에 "접속"만 함.
- 접속: `chmod 400 ~/Downloads/mission-key.pem` → `ssh -i ~/Downloads/mission-key.pem ec2-user@<퍼블릭IP>`.
- "post-quantum key exchange" 경고는 에러 아님(무시 가능).
- `Permission denied (publickey)` → 인스턴스에 연결된 키페어 이름이 실제로 그 키인지 확인.
- 인스턴스 안엔 코드 없음이 정상(.bash_history만 있음).

## 8. 메모장 vs 파일+clone 방식
git은 파일이 어떻게 만들어졌는지(메모장/에디터/복붙) 신경 안 씀. 파일 내용만 봄. 결과 동일.
메모장 이슈: 저장 시 `.txt` 자동 추가, 인코딩/줄바꿈 문제로 .md 깨짐 → **VS Code 추천**(확장자 자동변경 없음, 마크다운 미리보기, 터미널 내장).
