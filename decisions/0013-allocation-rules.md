# 0013. 오너십 규칙 엔진(allocation_rules) 도입

## Context
2026-09-23 데모 중, CloudFit 자체 EC2 인스턴스(i-05f7cdc5c5183e2ae, 이 프로젝트의 핵심 인프라)가
`ml/recommend.py`의 CPU/메모리 기준 저활용 판정 로직에 의해 다운사이즈 추천 대상으로 잘못 분류됨.
CPU/메모리 수치만으로는 "이게 우리 서비스의 핵심 인프라인지 아닌지"를 구분할 방법이 없었음.

## Decision
DB에 `allocation_rules` 테이블을 추가해서 인스턴스ID(패턴)-오너 매핑을 등록하고,
`ml/recommend.py`에 `resolve_owner()` 함수를 추가해 추천 생성 시 오너를 조회,
`CloudFit-Core-Infra`로 등록된 인스턴스는 downsize 추천에서 자동 제외한다.
`server/main.py`에 `/cost-by-owner` API를 추가해 오너별 비용 집계를 제공하고,
Grafana "비용 & 최적화" 대시보드에 오너별 비용 파이 차트 패널을 추가한다.

## Why
- CPU/메모리 수치는 "저활용"은 판단할 수 있어도 "이게 건드리면 안 되는 핵심 인프라인지"는 판단 못 함
- 오너 정보는 사람이 직접 등록해야 하는 메타데이터라 DB 테이블이 자연스러운 위치
- 각자 담당 클라우드가 다른 팀원(A-AWS, B-Azure, C-GCP)의 수집기 코드를 건드리지 않고,
  서버/추천 로직 레이어에서만 처리하면 브랜치/PR 충돌 없이 적용 가능

## 대안과의 비교
| 대안 | 장점 | 단점 |
|------|------|------|
| recommend.py에 인스턴스 ID 하드코딩 제외 | 구현 매우 간단 | 등록/변경 이력이 코드에 묻힘, 조회 불가 |
| 클라우드 콘솔에 실제 태그 부착 후 수집기가 태그 읽기 | 클라우드 네이티브 | AWS/Azure/GCP 수집기 3개 다 태그 조회 로직 추가, 팀원 3명 코드 수정 필요 |
| **DB 테이블(allocation_rules)로 중앙 관리 (채택)** | 단일 진실 공급원, 수집기 코드 무수정, API로 재사용 가능 | 실제 클라우드 태그와 별개 관리(동기화는 사람 책임) |

## Result
`i-05f7cdc5c5183e2ae` → `CloudFit-Core-Infra` 규칙 등록 후 `ml/recommend.py` 재실행 시
해당 인스턴스가 `keep`으로 판정됨을 확인. `resolve_owner()` 단독 테스트로 등록된 ID는
`CloudFit-Core-Infra`, 미등록 ID는 `Unassigned`를 정확히 반환함을 검증.
`/cost-by-owner` API 및 Grafana 파이 차트에서 `CloudFit-Core-Infra` 40% / `Unassigned` 60%
분할이 실제 데이터와 일치함을 확인.
