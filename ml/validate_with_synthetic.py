import pickle
import pandas as pd
import asyncpg
import asyncio

DATABASE_URL = "postgresql://finops:finops123@localhost:5432/finops_db"


async def fetch_synthetic_data():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("""
        SELECT cloud, instance_id, timestamp, cpu_avg,
               COALESCE(memory_avg, 0) AS memory_avg,
               COALESCE(disk_avg, 0) AS disk_avg,
               pattern
        FROM resource_metrics
        WHERE source = 'synthetic'
        ORDER BY timestamp
    """)
    await conn.close()
    return pd.DataFrame([dict(r) for r in rows])


def validate(df: pd.DataFrame, saved: dict) -> pd.DataFrame:
    """클라우드별 모델로 synthetic 데이터를 예측하고, pattern별 이상 판정 비율을 집계한다."""
    features = ['cpu_avg', 'memory_avg', 'disk_avg']
    results = []

    for cloud, cloud_group in df.groupby('cloud'):
        if cloud not in saved:
            print(f"[경고] {cloud}용 학습된 모델이 없음 - 스킵")
            continue

        model = saved[cloud]['model']
        scaler = saved[cloud]['scaler']

        X = cloud_group[features].fillna(0)
        X_scaled = scaler.transform(X)
        predictions = model.predict(X_scaled)  # -1: 이상, 1: 정상

        cloud_group = cloud_group.copy()
        cloud_group['anomaly'] = predictions == -1

        for pattern, pattern_group in cloud_group.groupby('pattern'):
            total = len(pattern_group)
            anomaly_count = int(pattern_group['anomaly'].sum())
            results.append({
                'cloud': cloud,
                'pattern': pattern,
                'total': total,
                'anomaly_count': anomaly_count,
                'anomaly_rate(%)': round(anomaly_count / total * 100, 1),
            })

    return pd.DataFrame(results)


async def main():
    with open('ml/model.pkl', 'rb') as f:
        saved = pickle.load(f)  # { cloud: {'model':..., 'scaler':...} }

    df = await fetch_synthetic_data()
    if df.empty:
        print("[INFO] synthetic 데이터 없음")
        return

    print(f"[INFO] synthetic 데이터 로드: {len(df)}건")
    print(df['cloud'].value_counts())

    result_df = validate(df, saved)

    print("\n=== 클라우드 x 패턴별 이상 판정 비율 ===")
    print(result_df.to_string(index=False))

    # 클라우드 구분 없이 패턴별 전체 평균도 같이 확인 (참고용)
    pattern_summary = (
        result_df.groupby('pattern')
        .apply(lambda g: round(g['anomaly_count'].sum() / g['total'].sum() * 100, 1))
        .reset_index(name='anomaly_rate(%)')
    )
    print("\n=== 패턴별 전체 평균 (클라우드 무관) ===")
    print(pattern_summary.to_string(index=False))

    result_df.to_csv('ml/validation_report.csv', index=False)
    print("\n[OK] 결과를 ml/validation_report.csv에 저장했습니다")

    print("""
[주의] 이 모델은 source='real' 데이터로만 학습했습니다.
synthetic 데이터는 real보다 절대값 자체가 훨씬 큽니다 (예: Azure synthetic 평균 59% vs real 평균 0.8%).
그래서 '정상' 패턴조차 real 기준 정상 범위를 벗어나 이상으로 판정될 수 있습니다.
이 경우 anomaly_rate 절대 수치보다, '정상' 패턴과 나머지 패턴들 사이에
상대적으로 비율 차이가 벌어지는지를 보는 것이 더 의미 있는 해석입니다.
""")


if __name__ == "__main__":
    asyncio.run(main())
