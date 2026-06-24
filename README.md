# CloudFit

멀티클라우드 환경에서의 자원 사용량 통합 분석 및 비용 최적화 추천 시스템

AWS, Azure, GCP의 VM 자원 사용량과 비용 정보를 통합 수집하고,
저활용·과대 스펙·비용 비효율 자원을 분석하여 최적화를 추천하는 FinOps 지원 시스템입니다.

## 팀 구성
- AWS 담당
- Azure 담당
- GCP 담당

## 기술 스택
- 언어: Python 3.11+
- 백엔드: FastAPI
- DB: PostgreSQL
- 수집: boto3(AWS), azure-mgmt-monitor(Azure), google-cloud-monitoring(GCP)
- 분석: scikit-learn (Isolation Forest)
- 시각화: Grafana + Prometheus
- 인프라: Docker, Docker Compose

## 진행 현황

### Day 01 - AWS 초기 세팅 (완료)
- AWS 계정 생성 및 루트 계정 MFA 설정
- IAM 수집기 사용자 생성 (ReadOnlyAccess 권한)
- 테스트 EC2 인스턴스 실행 (t3.micro, ap-northeast-2)
- boto3 기반 CloudWatch CPU 메트릭 첫 수집 성공

## 디렉터리 구조
\`\`\`
CloudFit/
├── aws/          # AWS 수집 모듈
├── azure/        # Azure 수집 모듈
├── gcp/          # GCP 수집 모듈
├── server/       # 중앙 통합 서버 (FastAPI)
└── docs/         # 문서, Runbook
\`\`\`
