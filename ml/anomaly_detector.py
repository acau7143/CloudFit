import argparse
import pickle
import pandas as pd
import asyncpg
import asyncio

DATABASE_URL = "postgresql://finops:finops123@localhost:5432/finops_db"


async def detect_and_save(full: bool = False):
    with open('ml/model.pkl', 'rb') as f:
        saved = pickle.load(f)  # { cloud: {'model':..., 'scaler':..., 'cpu_mean':..., 'cpu_std':...} }
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
        cpu_mean = saved[cloud]['cpu_mean']
        cpu_std = saved[cloud]['cpu_std']

        X = group[features].fillna(0)
        X_scaled = scaler.transform(X)

        # [decisions/0009] score는 참고 지표로 유지하되, 최종 이상 판정은
        # IsolationForest의 강제 비율이 아니라 cpu_avg의 평균±3표준편차 임계값으로 함
        scores = model.score_samples(X_scaled)

        group = group.copy()
        group['score'] = scores
        if cpu_std and cpu_std > 0:
            group['anomaly'] = (group['cpu_avg'] - cpu_mean).abs() > 3 * cpu_std
        else:
            # 표준편차가 0에 가까우면(완전히 고정된 값) 평균과 다르면 바로 이상으로 판정
            group['anomaly'] = group['cpu_avg'] != cpu_mean

        for _, row in group.iterrows():
            await conn.execute("""
                INSERT INTO anomaly_results
                    (cloud, instance_id, timestamp, cpu_avg, memory_avg, disk_avg, anomaly, score)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (cloud, instance_id, timestamp)
                DO UPDATE SET cpu_avg = EXCLUDED.cpu_avg,
                              memory_avg = EXCLUDED.memory_avg,
                              disk_avg = EXCLUDED.disk_avg,
                              anomaly = EXCLUDED.anomaly,
                              score = EXCLUDED.score,
                              detected_at = now()
            """, row['cloud'], row['instance_id'], row['timestamp'],
                 row['cpu_avg'], row['memory_avg'], row['disk_avg'],
                 bool(row['anomaly']), float(row['score']))
        anomaly_count = int(group['anomaly'].sum())
        total += len(group)
        total_anomaly += anomaly_count
        print(f"[{cloud}] 전체 {len(group)}건 중 이상 {anomaly_count}건 "
              f"(기준: {cpu_mean:.2f} ± {3*cpu_std:.2f})")
    print(f"[OK] 탐지 완료 - 전체 {total}건 중 이상 {total_anomaly}건")
    await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="이상탐지 실행")
    parser.add_argument("--full", action="store_true",
                         help="최근 1시간이 아닌 전체 real 데이터 재계산")
    args = parser.parse_args()
    asyncio.run(detect_and_save(full=args.full))
