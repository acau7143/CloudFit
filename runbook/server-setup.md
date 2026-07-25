# 중앙 서버 / DB 구축 및 실행 절차 (4주차)

## 1. 목적
수집기(AWS/Azure/GCP)가 보낸 자원·비용 데이터를 저장할 중앙 DB(PostgreSQL)와
REST API 서버(FastAPI)를 Docker Compose로 올린다.
팀원 전원이 `docker compose up` 한 줄로 동일한 환경을 재현할 수 있게 한다.

## 2. 구성
```
docker-compose.yml   # db + server 두 컨테이너 정의
db/schema.sql        # resource_metrics, cost_records 테이블 (컨테이너 최초 기동 시 자동 실행)
server/
  ├─ main.py         # FastAPI 앱 (엔드포인트)
  ├─ database.py     # 비동기 DB 연결(asyncpg + SQLAlchemy)
  ├─ Dockerfile
  └─ requirements.txt
```

## 3. 사전 준비
- Docker Desktop 설치 및 실행 (WSL2 백엔드 권장)
- 확인: `docker --version`, `docker compose version`

## 4. DB만 먼저 올리기
```bash
docker compose up -d db
docker ps                       # finops_db 컨테이너 Running 확인
docker logs finops_db           # 에러 없는지 확인
# 테이블 생성 확인
docker exec -it finops_db psql -U finops -d finops_db -c "\dt"
# resource_metrics, cost_records 두 테이블이 보이면 성공
```

> ⚠️ `schema.sql`은 **볼륨이 비어 있는 최초 기동 시에만** 자동 실행된다.
> 스키마를 고친 뒤 다시 반영하려면 볼륨을 지워야 한다:
> `docker compose down -v && docker compose up -d db`

## 5. 서버 로컬 실행 (개발용)
```bash
cd server
pip install -r requirements.txt
uvicorn main:app --reload
# http://localhost:8000/docs 에서 Swagger 확인
```

## 6. 엔드포인트
| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET  | /health   | 상태 확인 |
| POST | /resources | 자원 메트릭 저장 |
| GET  | /resources | 자원 메트릭 조회 (?cloud=AWS 필터) |
| POST | /costs     | 비용 레코드 저장 |
| GET  | /costs     | 비용 레코드 조회 (?cloud=AWS 필터) |

저장 테스트:
```bash
curl -s -X POST http://localhost:8000/resources \
  -H "Content-Type: application/json" \
  -d '{"cloud":"AWS","instance_id":"i-test001","timestamp":"2026-07-16T00:00:00Z","cpu_avg":15.3,"memory_avg":45.2,"disk_avg":60.1,"instance_type":"t3.micro","vcpu":2,"ram_gb":1.0}'

curl -s http://localhost:8000/resources | python3 -m json.tool
```

## 7. 전체 스택 올리기 (통합)
```bash
docker compose up --build
curl -s http://localhost:8000/health         # {"status":"ok"}
docker exec -it finops_db psql -U finops -d finops_db -c "SELECT COUNT(*) FROM resource_metrics;"
```

## 8. 트러블슈팅
- `port 5432 already in use` → 로컬에 다른 PostgreSQL이 떠 있음. 그것을 끄거나 compose 포트 매핑 변경.
- 서버가 DB보다 먼저 떠서 연결 실패 → `depends_on: condition: service_healthy`로 healthcheck 통과 후 기동하도록 설정돼 있음.
- 스키마 변경이 반영 안 됨 → 4번의 볼륨 삭제 후 재기동.
