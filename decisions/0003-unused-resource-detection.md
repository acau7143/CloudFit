# 0003. AWS 미사용 리소스 탐지 기준

## Context
FinOps Framework(Optimize 영역)의 낭비 제거 기능이 비어 있었음.
가장 흔한 낭비 유형인 미연결 EBS 볼륨, 미연결 Elastic IP부터 탐지 대상으로 정함.

## Decision
- 미연결 EBS 볼륨: `describe_volumes(Filters=[{'Name':'status','Values':['available']}])`
  로 조회되는 볼륨 전부 (상태가 `available`이면 어떤 인스턴스에도 안 붙어있다는 뜻)
- 미연결 Elastic IP: `describe_addresses()` 결과 중 `AssociationId` 키가 없는 것
- 탐지 결과는 `unused_resources` 테이블에 저장, 발견 시 Slack 알림(`notifier.py`) 호출

## Why
- 두 리소스 모두 AWS 콘솔의 "낭비 탐지"에서 가장 흔하게 잡히는 유형이고,
  판정 로직이 boto3 API 결과를 그대로 필터링하는 수준이라 구현 리스크가 낮음
- `resource_metrics`(CPU/메모리)와 달리 별도 시계열 수집 없이 현재 상태 조회만으로 판단 가능

## 검증 제약
- `ec2:CreateVolume` 권한이 EC2 역할(`CloudWatchAgentRole`)에 없어서, 실제 볼륨 생성으로
  미연결 상태를 재현하는 테스트는 하지 못함 (최소 권한 원칙상 의도적으로 막혀 있는 것으로 보임 —
  권한 확장은 팀 논의 필요)
- 대신 가상 테스트 데이터로 서버 저장 + Slack 알림 호출 경로까지는 검증 완료,
  실제 미연결 리소스가 생겼을 때 탐지되는지는 아직 실증되지 않음 — **팀 확인 필요**

## Result
- `collectors/aws_unused_detector.py` 작성 완료
- `unused_resources` 테이블에 AWS 행 저장 확인, Slack 알림 호출 로직 확인 (Webhook URL 미확보로 실전송 테스트는 보류)
