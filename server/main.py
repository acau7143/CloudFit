import hashlib
import hmac
import json
import os
import time
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db

app = FastAPI(title="멀티클라우드 FinOps API")

SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET", "")


# --- 요청 스키마 (팀 공통 형식) ---

class ResourceMetricIn(BaseModel):
    cloud: str                              # 'AWS' / 'Azure' / 'GCP'
    instance_id: str
    timestamp: str                          # ISO 8601: '2026-07-16T00:00:00Z'
    cpu_avg: float
    memory_avg: Optional[float] = None
    disk_avg: Optional[float] = None
    instance_type: Optional[str] = None
    vcpu: Optional[int] = None
    ram_gb: Optional[float] = None


class CostRecordIn(BaseModel):
    cloud: str
    date: str                               # 'YYYY-MM-DD'
    cost_usd: float
    currency: str = "USD"
    service: Optional[str] = None
    granularity: str = "DAILY"


class UnusedResourceIn(BaseModel):
    cloud: str                              # 'AWS' / 'Azure' / 'GCP'
    resource_type: str                      # 'disk' / 'ip' / 'volume'
    resource_id: str
    reason: Optional[str] = None


class AskIn(BaseModel):
    question: str                           # 자연어 질문 (예: '이번달 GCP 비용 얼마야?')


# --- 엔드포인트 ---

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/resources", status_code=201)
async def save_resource(metric: ResourceMetricIn, db: AsyncSession = Depends(get_db)):
    # [5주차] 중복 방지: (cloud, instance_id, timestamp)가 같으면 덮어쓴다.
    #   재전송해도 행이 두 배로 늘지 않음. UNIQUE 제약(uq_resource_cloud_instance_ts)과 짝.
    sql = text("""
        INSERT INTO resource_metrics
            (cloud, instance_id, timestamp, cpu_avg, memory_avg, disk_avg,
             instance_type, vcpu, ram_gb)
        VALUES
            (:cloud, :instance_id, :timestamp, :cpu_avg, :memory_avg, :disk_avg,
             :instance_type, :vcpu, :ram_gb)
        ON CONFLICT (cloud, instance_id, timestamp)
        DO UPDATE SET
            cpu_avg = EXCLUDED.cpu_avg,
            memory_avg = EXCLUDED.memory_avg,
            disk_avg = EXCLUDED.disk_avg,
            instance_type = EXCLUDED.instance_type,
            vcpu = EXCLUDED.vcpu,
            ram_gb = EXCLUDED.ram_gb
    """)
    data = metric.model_dump()
    # asyncpg는 문자열이 아니라 datetime 객체를 요구 → ISO 문자열을 변환
    data["timestamp"] = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
    await db.execute(sql, data)
    await db.commit()
    return {"status": "saved"}


@app.get("/resources")
async def get_resources(cloud: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    if cloud:
        result = await db.execute(
            text("SELECT * FROM resource_metrics WHERE cloud = :cloud "
                 "ORDER BY timestamp DESC LIMIT 100"),
            {"cloud": cloud},
        )
    else:
        result = await db.execute(
            text("SELECT * FROM resource_metrics ORDER BY timestamp DESC LIMIT 100")
        )
    return [dict(row._mapping) for row in result.fetchall()]


@app.post("/costs", status_code=201)
async def save_cost(record: CostRecordIn, db: AsyncSession = Depends(get_db)):
    # [5주차] 중복 방지: (cloud, date, service)가 같으면 덮어쓴다.
    #   수집기가 최근 7일을 매번 다시 긁어오므로, 재전송 시 같은 날짜/서비스 행이
    #   쌓이지 않고 최신 값으로 갱신됨. UNIQUE 제약(uq_cost_cloud_date_service)과 짝.
    sql = text("""
        INSERT INTO cost_records (cloud, date, cost_usd, currency, service, granularity)
        VALUES (:cloud, :date, :cost_usd, :currency, :service, :granularity)
        ON CONFLICT (cloud, date, service)
        DO UPDATE SET
            cost_usd = EXCLUDED.cost_usd,
            currency = EXCLUDED.currency,
            granularity = EXCLUDED.granularity
    """)
    data = record.model_dump()
    # DATE 컬럼도 문자열이 아니라 date 객체를 요구 → 변환
    data["date"] = date.fromisoformat(data["date"])
    await db.execute(sql, data)
    await db.commit()
    return {"status": "saved"}


@app.get("/costs")
async def get_costs(cloud: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    if cloud:
        result = await db.execute(
            text("SELECT * FROM cost_records WHERE cloud = :cloud "
                 "ORDER BY date DESC LIMIT 100"),
            {"cloud": cloud},
        )
    else:
        result = await db.execute(
            text("SELECT * FROM cost_records ORDER BY date DESC LIMIT 100")
        )
    return [dict(row._mapping) for row in result.fetchall()]


@app.get("/anomalies")
async def get_anomalies(
    cloud: Optional[str] = None,
    only_anomaly: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """이상탐지 결과 조회 (기본: 이상 건만, cloud로 추가 필터 가능)"""
    conditions = []
    params = {}
    if cloud:
        conditions.append("cloud = :cloud")
        params["cloud"] = cloud
    if only_anomaly:
        conditions.append("anomaly = TRUE")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = text(f"""
        SELECT cloud, instance_id, timestamp, cpu_avg, anomaly, score
        FROM anomaly_results
        {where}
        ORDER BY timestamp DESC
        LIMIT 100
    """)
    result = await db.execute(sql, params)
    return [dict(row._mapping) for row in result.fetchall()]


@app.get("/recommendations")
async def get_recommendations(
    cloud: Optional[str] = None,
    recommendation: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """비용 최적화 추천 조회 (cloud, recommendation으로 필터 가능)"""
    conditions = []
    params = {}
    if cloud:
        conditions.append("cloud = :cloud")
        params["cloud"] = cloud
    if recommendation:
        conditions.append("recommendation = :recommendation")
        params["recommendation"] = recommendation
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = text(f"""
        SELECT cloud, instance_id, avg_cpu_7d, total_cost_7d, recommendation, reason, generated_at
        FROM recommendations
        {where}
        ORDER BY generated_at DESC
        LIMIT 100
    """)
    result = await db.execute(sql, params)
    return [dict(row._mapping) for row in result.fetchall()]


@app.post("/unused-resources", status_code=201)
async def save_unused_resource(item: UnusedResourceIn, db: AsyncSession = Depends(get_db)):
    sql = text("""
        INSERT INTO unused_resources (cloud, resource_type, resource_id, reason)
        VALUES (:cloud, :resource_type, :resource_id, :reason)
    """)
    await db.execute(sql, item.model_dump())
    await db.commit()
    return {"status": "saved"}


@app.get("/unused-resources")
async def get_unused_resources(
    cloud: Optional[str] = None,
    only_active: bool = True,
    db: AsyncSession = Depends(get_db)
):
    """미사용 리소스 조회 (기본: 아직 안 정리된 것만, cloud로 추가 필터 가능)"""
    conditions = []
    params = {}
    if cloud:
        conditions.append("cloud = :cloud")
        params["cloud"] = cloud
    if only_active:
        conditions.append("resolved_at IS NULL")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = text(f"""
        SELECT cloud, resource_type, resource_id, reason, detected_at, resolved_at
        FROM unused_resources
        {where}
        ORDER BY detected_at DESC
        LIMIT 100
    """)
    result = await db.execute(sql, params)
    return [dict(row._mapping) for row in result.fetchall()]


@app.get("/forecast")
async def get_forecast(cloud: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """비용 예측 조회 (cloud로 필터 가능). 같은 날짜에 여러 번 예측이 쌓여도
    (cloud, forecast_date)별 가장 최근 예측(generated_at 최신) 하나만 반환한다."""
    if cloud:
        result = await db.execute(
            text("""
                SELECT DISTINCT ON (cloud, forecast_date)
                    cloud, forecast_date, predicted_cost, lower_bound, upper_bound, generated_at
                FROM cost_forecast
                WHERE cloud = :cloud
                ORDER BY cloud, forecast_date, generated_at DESC
            """),
            {"cloud": cloud},
        )
    else:
        result = await db.execute(
            text("""
                SELECT DISTINCT ON (cloud, forecast_date)
                    cloud, forecast_date, predicted_cost, lower_bound, upper_bound, generated_at
                FROM cost_forecast
                ORDER BY cloud, forecast_date, generated_at DESC
            """)
        )
    return [dict(row._mapping) for row in result.fetchall()]


def _extract_cloud(question: str):
    """질문 문장에서 클라우드 이름을 찾는다. 대소문자 구분 없이 매칭."""
    q = question.upper()
    if "AWS" in q:
        return "AWS"
    if "AZURE" in q:
        return "Azure"
    if "GCP" in q:
        return "GCP"
    return None


async def generate_answer(question: str, db: AsyncSession) -> dict:
    """[10주차] 규칙 기반 질문-응답 핵심 로직. LLM을 호출하지 않고, 정해진 키워드
    패턴을 순서대로 검사해서 처음 매칭되는 템플릿의 SQL을 실행하고 문장으로 답한다.
    /ask(API), /slack/ask(슬래시 커맨드), /slack/interact(버튼 클릭) 세 곳이 전부
    이 함수 하나를 재사용한다 - 답변 로직은 한 곳에만 있고, 입구만 다르다."""
    q = question
    cloud = _extract_cloud(q)
    target = cloud or "전체"

    if "비용" in q and ("이번달" in q or "이번 달" in q):
        conditions = ["date >= date_trunc('month', CURRENT_DATE)"]
        params = {}
        if cloud:
            conditions.append("cloud = :cloud")
            params["cloud"] = cloud
        where = "WHERE " + " AND ".join(conditions)
        result = await db.execute(
            text(f"SELECT COALESCE(SUM(cost_usd), 0) AS total FROM cost_records {where}"),
            params,
        )
        total = result.scalar()
        return {"answer": f"이번 달 {target} 비용은 ${total:.2f}입니다.", "matched_template": "monthly_cost"}

    if "이상탐지" in q or ("이상" in q and "건" in q):
        conditions = ["anomaly = TRUE", "timestamp >= NOW() - INTERVAL '7 days'"]
        params = {}
        if cloud:
            conditions.append("cloud = :cloud")
            params["cloud"] = cloud
        where = "WHERE " + " AND ".join(conditions)
        result = await db.execute(text(f"SELECT COUNT(*) FROM anomaly_results {where}"), params)
        count = result.scalar()
        return {"answer": f"최근 7일간 {target} 이상탐지 건수는 {count}건입니다.", "matched_template": "anomaly_count"}

    if "미사용" in q or "안쓰는" in q or "안 쓰는" in q:
        conditions = ["resolved_at IS NULL"]
        params = {}
        if cloud:
            conditions.append("cloud = :cloud")
            params["cloud"] = cloud
        where = "WHERE " + " AND ".join(conditions)
        result = await db.execute(text(f"SELECT COUNT(*) FROM unused_resources {where}"), params)
        count = result.scalar()
        return {"answer": f"현재 정리 안 된 {target} 미사용 리소스는 {count}건입니다.", "matched_template": "unused_count"}

    if "다운사이즈" in q or "추천" in q:
        conditions = ["recommendation = 'downsize'"]
        params = {}
        if cloud:
            conditions.append("cloud = :cloud")
            params["cloud"] = cloud
        where = "WHERE " + " AND ".join(conditions)
        result = await db.execute(text(f"SELECT COUNT(*) FROM recommendations {where}"), params)
        count = result.scalar()
        return {"answer": f"{target} 다운사이즈 추천 대상은 {count}건입니다.", "matched_template": "downsize_count"}

    if "예측" in q:
        conditions = ["forecast_date >= CURRENT_DATE"]
        params = {}
        if cloud:
            conditions.append("cloud = :cloud")
            params["cloud"] = cloud
        where = "WHERE " + " AND ".join(conditions)
        result = await db.execute(
            text(f"""
                SELECT DISTINCT ON (forecast_date) forecast_date, predicted_cost
                FROM cost_forecast
                {where}
                ORDER BY forecast_date ASC, generated_at DESC
                LIMIT 1
            """),
            params,
        )
        row = result.fetchone()
        if row is None:
            return {"answer": f"{target} 예측 데이터가 아직 없습니다.", "matched_template": "forecast"}
        return {
            "answer": f"{target}의 {row.forecast_date} 예상 비용은 ${row.predicted_cost:.2f}입니다.",
            "matched_template": "forecast",
        }

    return {
        "answer": (
            "이해하지 못한 질문이에요. 지원하는 질문 예시: "
            "'이번달 GCP 비용 얼마야?', '이상탐지 몇 건?', '미사용 리소스 몇 개?', "
            "'다운사이즈 추천 몇 건?', 'AWS 비용 예측 얼마?'"
        ),
        "matched_template": None,
    }


@app.post("/ask")
async def ask(payload: AskIn, db: AsyncSession = Depends(get_db)):
    """[10주차] JSON으로 직접 질문을 보낼 때 쓰는 API. 핵심 로직은 generate_answer()."""
    return await generate_answer(payload.question, db)


# --- Slack 연동 ---

QUESTION_BUTTONS = [
    ("이번달 비용", "이번달 비용 얼마야?"),
    ("이상탐지 건수", "이상탐지 몇 건?"),
    ("미사용 리소스", "미사용 리소스 몇 개?"),
    ("다운사이즈 추천", "다운사이즈 추천 몇 건?"),
    ("비용 예측", "비용 예측 얼마야?"),
]


def _build_button_blocks():
    """Slack Block Kit 버튼 5개 생성. value에 실제 질문 문장을 그대로 넣어서
    버튼 클릭도 generate_answer()를 재사용한다."""
    elements = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "value": question_text,
            "action_id": f"ask_{i}",
        }
        for i, (label, question_text) in enumerate(QUESTION_BUTTONS)
    ]
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": "*어떤 게 궁금하세요?*"}},
        {"type": "actions", "elements": elements},
    ]


def verify_slack_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """Slack 공식 서명 검증(v0). 없으면 아무나 이 URL로 가짜 요청을 보낼 수 있음.
    5분 넘은 요청은 재전송 공격 가능성 있어 거부."""
    if not SLACK_SIGNING_SECRET or not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 60 * 5:
            return False
    except ValueError:
        return False
    base = f"v0:{timestamp}:{raw_body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode(), base.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


@app.post("/slack/ask")
async def slack_ask(request: Request, db: AsyncSession = Depends(get_db)):
    """Slack 슬래시 커맨드(/finops)용. 질문 없이 치면 버튼 메뉴, 질문 붙이면 바로 답."""
    raw_body = await request.body()
    if not verify_slack_signature(
        raw_body,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
    ):
        raise HTTPException(status_code=401, detail="Slack 서명 검증 실패")

    form = await request.form()
    question = (form.get("text") or "").strip()

    if not question:
        return {"response_type": "ephemeral", "blocks": _build_button_blocks()}

    result = await generate_answer(question, db)
    return {"response_type": "in_channel", "text": result["answer"]}


@app.post("/slack/interact")
async def slack_interact(request: Request, db: AsyncSession = Depends(get_db)):
    """Slack 버튼 클릭용. 버튼 value(질문 문장)를 generate_answer()에 그대로 넘긴다."""
    raw_body = await request.body()
    if not verify_slack_signature(
        raw_body,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        request.headers.get("X-Slack-Signature", ""),
    ):
        raise HTTPException(status_code=401, detail="Slack 서명 검증 실패")

    form = await request.form()
    payload = json.loads(form.get("payload", "{}"))
    question = payload["actions"][0]["value"]

    result = await generate_answer(question, db)
    return {"response_type": "in_channel", "text": result["answer"], "replace_original": True}
