import asyncpg
import asyncio
from datetime import datetime, timezone

DATABASE_URL = "postgresql://finops:finops123@localhost:5432/finops_db"

CPU_THRESHOLD = 15.0  # 이 값(%) 미만이면 저활용으로 판단


async def fetch_cpu_by_cloud(conn):
    rows = await conn.fetch("""
        SELECT cloud, instance_id, AVG(cpu_avg) AS avg_cpu_7d
        FROM resource_metrics
        WHERE source = 'real'
          AND cpu_avg IS NOT NULL
          AND timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY cloud, instance_id
    """)
    return {r['cloud']: dict(r) for r in rows}


async def fetch_cost_by_cloud(conn):
    rows = await conn.fetch("""
        SELECT cloud, SUM(cost_usd) AS total_cost_7d
        FROM cost_records
        WHERE date >= (CURRENT_DATE - INTERVAL '7 days')
        GROUP BY cloud
    """)
    return {r['cloud']: r['total_cost_7d'] for r in rows}


def judge(avg_cpu, total_cost):
    # [8주차] CPU 7일 평균 < 15%이면서 비용이 발생 중이면 downsize
    # synthetic 인스턴스는 cost_records에 없으므로(실제 비용 없음) 자동 제외됨
    if total_cost is None or total_cost <= 0:
        return 'keep', 'DB에 최근 7일 비용 데이터 없음 - 판단 보류'
    if avg_cpu is not None and avg_cpu < CPU_THRESHOLD:
        return 'downsize', f'최근 7일 평균 CPU {avg_cpu:.1f}%로 낮은데 비용은 ${total_cost:.2f} 발생 중'
    return 'keep', f'최근 7일 평균 CPU {avg_cpu:.1f}% - 정상 범위'



async def generate_recommendations():
    conn = await asyncpg.connect(DATABASE_URL)

    cpu_by_cloud = await fetch_cpu_by_cloud(conn)
    cost_by_cloud = await fetch_cost_by_cloud(conn)

    clouds = set(cpu_by_cloud.keys()) | set(cost_by_cloud.keys())
    if not clouds:
        print("[INFO] 최근 7일 real 데이터 없음")
        await conn.close()
        return

    now = datetime.now(timezone.utc)
    results = []
    for cloud in sorted(clouds):
        cpu_row = cpu_by_cloud.get(cloud)
        avg_cpu = cpu_row['avg_cpu_7d'] if cpu_row else None
        instance_id = cpu_row['instance_id'] if cpu_row else 'unknown'
        total_cost = cost_by_cloud.get(cloud)

        recommendation, reason = judge(avg_cpu, total_cost)

        await conn.execute("""
            INSERT INTO recommendations
                (cloud, instance_id, avg_cpu_7d, total_cost_7d, recommendation, reason, generated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (cloud, instance_id, generated_at) DO NOTHING
        """, cloud, instance_id, avg_cpu, total_cost, recommendation, reason, now)

        results.append((cloud, instance_id, avg_cpu, total_cost, recommendation))
        cpu_str = f"CPU {avg_cpu:.1f}%" if avg_cpu is not None else "CPU 데이터 없음"
        cost_str = f"비용 ${total_cost:.2f}" if total_cost is not None else "비용 데이터 없음"
        print(f"[{cloud}] {instance_id} - {cpu_str} / {cost_str} -> {recommendation}")

    print(f"[OK] 추천 {len(results)}건 저장 완료")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(generate_recommendations())
