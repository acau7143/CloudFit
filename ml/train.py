import pandas as pd
import pickle
import asyncpg
import asyncio
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

DATABASE_URL = "postgresql://finops:finops123@localhost:5432/finops_db"

async def fetch_training_data():
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("""
        SELECT cloud, cpu_avg, COALESCE(memory_avg, 0) AS memory_avg,
               COALESCE(disk_avg, 0) AS disk_avg, timestamp
        FROM resource_metrics
        WHERE cpu_avg IS NOT NULL
        ORDER BY timestamp
    """)
    await conn.close()
    return pd.DataFrame([dict(r) for r in rows])

def train_model_for_cloud(df_cloud, cloud):
    features = ['cpu_avg', 'memory_avg', 'disk_avg']
    X = df_cloud[features].fillna(0)
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
    model.fit(X_scaled)
    print(f"[OK] {cloud} 모델 학습 완료 - 학습 데이터: {len(df_cloud)}건")
    return {'model': model, 'scaler': scaler}

def train_all(df):
    saved = {}
    for cloud, group in df.groupby('cloud'):
        if len(group) < 20:
            print(f"[경고] {cloud} 데이터가 {len(group)}건뿐 - 학습 스킵")
            continue
        saved[cloud] = train_model_for_cloud(group, cloud)
    with open('ml/model.pkl', 'wb') as f:
        pickle.dump(saved, f)
    print(f"[OK] 전체 저장 완료 - 클라우드: {list(saved.keys())}")
    return saved

if __name__ == "__main__":
    df = asyncio.run(fetch_training_data())
    print(f"[INFO] 학습 데이터 로드: {len(df)}건")
    print(df['cloud'].value_counts())
    train_all(df)
