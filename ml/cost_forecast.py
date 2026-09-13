import pandas as pd
import asyncpg
import asyncio
import argparse
from prophet import Prophet

DATABASE_URL = "postgresql://finops:finops123@localhost:5432/finops_db"


async def fetch_cost_history(cloud: str) -> pd.DataFrame:
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("""
        SELECT date, SUM(cost_usd) AS cost
        FROM cost_records
        WHERE cloud = $1
        GROUP BY date
        ORDER BY date
    """, cloud)
    await conn.close()
    # Prophet은 컬럼명이 반드시 ds(날짜), y(값)여야 함
    return pd.DataFrame([{"ds": r["date"], "y": r["cost"]} for r in rows])


async def forecast_and_save(cloud: str, dry_run: bool = False, days: int = 7):
    df = await fetch_cost_history(cloud)
    if len(df) < 7:
        print(f"[경고] {cloud} 데이터가 {len(df)}일치뿐 - 예측 신뢰도 낮음, 그래도 진행")

    model = Prophet()
    model.fit(df)
    future = model.make_future_dataframe(periods=days)
    forecast = model.predict(future)

    result = forecast[['ds', 'yhat', 'yhat_lower', 'yhat_upper']].tail(days)
    print(f"[{cloud}] 향후 {days}일 예측:")
    print(result.to_string(index=False))

    if not dry_run:
        conn = await asyncpg.connect(DATABASE_URL)
        for _, row in result.iterrows():
            await conn.execute("""
                INSERT INTO cost_forecast (cloud, forecast_date, predicted_cost, lower_bound, upper_bound)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (cloud, forecast_date, generated_at) DO NOTHING
            """, cloud, row['ds'].date(), float(row['yhat']),
                 float(row['yhat_lower']), float(row['yhat_upper']))
        await conn.close()
        print(f"[OK] {cloud} 예측 결과 저장 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloud", required=True, choices=["AWS", "Azure", "GCP"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(forecast_and_save(args.cloud, dry_run=args.dry_run))
