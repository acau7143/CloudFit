from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db

app = FastAPI(title="멀티클라우드 FinOps API")


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


# --- 엔드포인트 ---

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/resources", status_code=201)
async def save_resource(metric: ResourceMetricIn, db: AsyncSession = Depends(get_db)):
    sql = text("""
        INSERT INTO resource_metrics
            (cloud, instance_id, timestamp, cpu_avg, memory_avg, disk_avg,
             instance_type, vcpu, ram_gb)
        VALUES
            (:cloud, :instance_id, :timestamp, :cpu_avg, :memory_avg, :disk_avg,
             :instance_type, :vcpu, :ram_gb)
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
    sql = text("""
        INSERT INTO cost_records (cloud, date, cost_usd, currency, service, granularity)
        VALUES (:cloud, :date, :cost_usd, :currency, :service, :granularity)
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
