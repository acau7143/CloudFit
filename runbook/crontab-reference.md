# 운영 VM crontab 기록

> 2026-10-24 기준, 현재 운영 중인 VM에서 `crontab -l`로 확인한 원문이다.
> 지금까지 저장소에 cron 설정이 없어서 새 환경에서 무엇을 어떤 주기로 돌려야 하는지 알 수 없었다.
> `decisions/0015` 단계 2에서 이 내용을 설치 스크립트가 등록하는 템플릿으로 옮긴다.

## 전제

- 모든 줄이 `logs/` 아래로 출력을 리다이렉트한다. **`logs/` 폴더가 없으면 cron이 조용히 실패**하므로
  `mkdir -p ~/CloudFit/logs`가 먼저 필요하다. (`logs/`는 `.gitignore` 대상이라 저장소에 없다.)
- 시각(`0 9 * * *` 등)은 **VM의 시간대 기준**이다. 새 환경에서 `timedatectl`로 시간대를 확인할 것.
- 환경 설정은 프로젝트 루트의 `.env`에서 읽는다 (`.env.example` 참고).

## AWS EC2 — 서버 VM이자 수집·ML 배치 실행 VM

사용자 `ec2-user`, 시스템 `python3` 사용. 중앙 서버(Docker Compose)가 같은 VM에서 돈다.
이 VM의 Python은 3.9라 boto3의 "Python 3.9 지원 종료" 경고가 cron 로그에 매번 남는다 (동작에는 영향 없음).

```cron
*/5 * * * * cd /home/ec2-user/CloudFit && python3 collectors/aws_exporter.py >> logs/aws_resource.log 2>&1
0 9 * * * cd /home/ec2-user/CloudFit && python3 collectors/aws_exporter.py --costs >> logs/aws_cost.log 2>&1
*/10 * * * * cd /home/ec2-user/CloudFit && python3 ml/anomaly_detector.py >> logs/anomaly.log 2>&1
0 3 * * 0 cd /home/ec2-user/CloudFit && python3 ml/train.py >> logs/train.log 2>&1
15 9 * * * cd /home/ec2-user/CloudFit && python3 collectors/aws_unused_detector.py >> logs/unused_resource.log 2>&1
30 9 * * * cd /home/ec2-user/CloudFit && python3 ml/cost_forecast.py --cloud AWS >> logs/forecast.log 2>&1
35 9 * * * cd /home/ec2-user/CloudFit && python3 ml/cost_forecast.py --cloud Azure >> logs/forecast.log 2>&1
40 9 * * * cd /home/ec2-user/CloudFit && python3 ml/cost_forecast.py --cloud GCP >> logs/forecast.log 2>&1
45 9 * * * cd /home/ec2-user/CloudFit && python3 server/budget_alert.py >> logs/budget_alert.log 2>&1
50 9 * * * cd /home/ec2-user/CloudFit && python3 ml/recommend.py >> logs/recommend.log 2>&1
```

| 주기 | 작업 | 비고 |
|---|---|---|
| 5분 | AWS 자원 수집 | |
| 매일 09:00 | AWS 비용 수집 (`--costs`) | |
| 10분 | 이상탐지 | `anomaly_results` 갱신, 정상→이상 전환 시 Slack |
| 매주 일 03:00 | 모델 학습 | 최근 7일 데이터 사용 |
| 매일 09:15 | 미사용 리소스 탐지 | 연속 2회 탐지 시 Slack |
| 매일 09:30/35/40 | 비용 예측 (AWS/Azure/GCP) | Prophet, 7일치 이상 필요 |
| 매일 09:45 | 예산 초과 알림 | `BUDGET_*` 설정한 클라우드만 |
| 매일 09:50 | 비용 최적화 추천 | 예측·예산 이후에 실행되도록 순서가 정해져 있음 |

## GCP VM

사용자 `user`, 가상환경 `/home/user/finops-env`.

```cron
*/5 * * * * cd /home/user/CloudFit && /home/user/finops-env/bin/python3 collectors/gcp_exporter.py >> logs/gcp_resource.log 2>&1
0 9 * * * cd /home/user/CloudFit && /home/user/finops-env/bin/python3 collectors/gcp_exporter.py --costs >> logs/gcp_cost.log 2>&1
15 9 * * * cd ~/CloudFit && /home/user/finops-env/bin/python3 collectors/gcp_unused_detector.py >> logs/unused_resource.log 2>&1
```

수정 이력:

- 2026-10-24: 세 번째 줄(미사용 탐지)이 가상환경이 아닌 시스템 `python3`로 실행돼 `ModuleNotFoundError: dotenv`로
  실패하고 있었다. 가상환경 파이썬으로 교체했다 (위 crontab은 교체 후 상태). 설치 스크립트도 가상환경 파이썬으로 통일해야 한다.

알려진 불일치:

- `gcp_exporter.py`는 `--costs` 인자를 파싱하지 않는다 (`--dry-run`만 확인). 그래서 5분 주기 실행과
  매일 09:00 실행이 **같은 동작**(자원 + 비용 수집·전송)을 한다. 비용 조회(BigQuery)가 5분마다 실행되는 셈이다.
  동작을 바꿀지 여부는 별도로 결정한다.

## Azure VM

> **TODO(B)**: Azure VM에서 `crontab -l` 결과를 받아 여기에 추가한다.
