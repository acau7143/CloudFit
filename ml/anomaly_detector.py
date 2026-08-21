import argparse
import pickle
import pandas as pd
import asyncpg
import asyncio

DATABASE_URL = "postgresql://finops:finops123@localhost:5432/finops_db"

async def detect_and_save(full: bool = False):
    with open('ml/model.pkl', 'rb') as f:
        saved = pickle.load(f)  # { cloud: {'model':..., 'scaler':...} }
    conn = await asyncpg.connect(DATABASE_URL)
    if full:
        rows = await conn.fetch("""
            SELECT cloud, instance_id, timestamp, cpu_avg,
                   COALESCE(memory_avg, 0) AS memory_avg,
                   COALESCE(disk_avg, 0) AS disk_avg
            FROM resource_metrics
            WHERE source = 'real'
            ORDER BY timestamp
        """)
    else:
        rows = await conn.fetch("""
            SELECT cloud, instance_id, timestamp, cpu_avg,
                   COALESCE(memory_avg, 0) AS memory_avg,
                   COALESCE(disk_avg, 0) AS disk_avg
            FROM resource_metrics
            WHERE timestamp >= NOW() - INTERVAL '1 hour'
              AND source = 'real'
            ORDER BY timestamp
        """)
    if not rows:
        print("[INFO] 대상 데이터 없음 (source='real')")
        await conn.close()
        return
    df = pd.DataFrame([dict(r) for r in rows])
    features = ['cpu_avg', 'memory_avg', 'disk_avg']
    total, total_anomaly = 0, 0
    for cloud, group in df.groupby('cloud'):
        if cloud not in saved:
            print(f"[경고] {cloud}용 학습된 모델이 없음 - 스킵")
            continue
        model = saved[cloud]['model']
        scaler = saved[cloud]['scaler']
        X = group[features].fillna(0)
        X_scaled = scaler.transform(X)
        predictions = model.predict(X_scaled)   # -1: 이상, 1: 정상
        scores = model.score_samples(X_scaled)
        group = group.copy()
        group['anomaly'] = predictions == -1
        group['score'] = scores
        for _, row in group.iterrows():
            await conn.execute("""
                INSERT INTO anomaly_results
                    (cloud, instance_id, timestamp, cpu_avg, anomaly, score)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (cloud, instance_id, timestamp)
                DO UPDATE SET cpu_avg = EXCLUDED.cpu_avg,
                              anomaly = EXCLUDED.anomaly,
                              score = EXCLUDED.score,
                              detected_at = now()
            """, row['cloud'], row['instance_id'], row['timestamp'],
                 row['cpu_avg'], bool(row['anomaly']), float(row['score']))
        anomaly_count = int(group['anomaly'].sum())
        total += len(group)
        total_anomaly += anomaly_count
        print(f"[{cloud}] 전체 {len(group)}건 중 이상 {anomaly_count}건")
    print(f"[OK] 탐지 완료 - 전체 {total}건 중 이상 {total_anomaly}건")
    await conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="이상탐지 실행")
    parser.add_argument("--full", action="store_true",
                         help="최근 1시간이 아닌 전체 real 데이터 재계산")
    args = parser.parse_args()
    asyncio.run(detect_and_save(full=args.full))
