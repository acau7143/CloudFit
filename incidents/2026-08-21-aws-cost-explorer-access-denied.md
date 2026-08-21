# INC-001 — AWS Cost Explorer 비용 수집 중단 (IAM 권한 누락)

- **발생 기간**: 2026-07-29 ~ 2026-08-21 (약 3주 4일)
- **발견일**: 2026-08-21
- **발견자**: A
- **영향 범위**: AWS 비용 데이터(`cost_records`, cloud='AWS')만 영향. AWS 자원 수집(`resource_metrics`)과 Azure/GCP는 정상 동작
- **심각도**: 중 — 데이터 유실은 없었으나(비용 자체가 기록 안 된 것), 이 기간 AWS 비용 기반 기능(추천 로직 등)이 사실상 무력화됨

## 증상
- `ml/recommend.py` 최초 실행 시 AWS만 "비용 데이터 없음"으로 나와 `keep`으로 잘못 판단됨 (실제로는 CPU 2.9%로 가장 저활용 상태였는데도 추천 대상에서 누락)
- `cost_records` 테이블 조회 결과 AWS 최종 데이터가 2026-07-29에서 멈춰있었음 (Azure/GCP는 매일 정상 적재)

## 원인
- `logs/aws_cost.log` 확인 결과, 6주차에 등록한 비용 수집 크론(`0 9 * * *`, `aws_exporter.py --costs`)이 매일 정상 실행은 되고 있었으나, Cost Explorer API 호출 시 아래 에러로 계속 실패하고 있었음:

  ```
  AccessDeniedException: User: arn:aws:sts::379057358736:assumed-role/CloudWatchAgentRole/i-05f7cdc5c5183e2ae
  is not authorized to perform: ce:GetCostAndUsage on resource: arn:aws:ce:us-east-1:379057358736:/GetCostAndUsage
  ```

- EC2 인스턴스에 연결된 IAM 역할이 `CloudWatchAgentRole`인데, 이름 그대로 CloudWatch 지표 수집용 권한만 있고 Cost Explorer(`ce:GetCostAndUsage`) 권한이 없었음
- 정확히 언제, 왜 이 역할로 변경/재연결됐는지는 확인하지 못함 — 크론 자체는 살아있었기 때문에 실패가 로그로만 남고 별도 알림 없이 조용히 누적됨

## 조치
- AWS 콘솔 → IAM → `CloudWatchAgentRole`에 Cost Explorer 읽기 권한 정책 추가
- `python3 collectors/aws_exporter.py --costs` 수동 재실행으로 복구 확인 (성공 40 / 실패 0)
- 이후 `ml/recommend.py` 재실행 → AWS 비용 데이터 정상 반영, `downsize` 추천 정상 산출

## 재발 방지 아이디어 (미착수, 팀 논의 필요)
- 비용 수집 크론이 연속 실패할 경우 알림(예: 로그 grep 기반 간단 체크 스크립트, 혹은 Slack/이메일 알림)이 없어서 3주간 아무도 몰랐음 — 최소한 "최근 N일 비용 데이터 없음"을 감지하는 헬스체크가 필요해 보임
- IAM 역할 이름(`CloudWatchAgentRole`)과 실제 용도(비용 수집까지 포함)가 불일치 — 역할 이름을 정리하거나, 최소한 어떤 권한이 왜 붙어있는지 팀 문서에 남겨두는 게 좋을 듯
