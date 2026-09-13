import asyncpg
import asyncio
from datetime import datetime, timezone

DATABASE_URL = "postgresql://finops:finops123@localhost:5432/finops_db"

CPU_THRESHOLD = 15.0  # 이 값(%) 미만이면 저활용으로 판단
MEM_THRESHOLD = 30.0  # [9주차] 메모리도 이 값(%) 미만이어야 downsize - CPU만 낮고 메모리를 많이 쓰면 잘못된 추천이 됨

# [10주차] 예약 인스턴스(RI) 추천 기준
UPTIME_THRESHOLD = 0.90          # 최근 7일 가동 시간 비율이 이 값 이상이면 RI 추천
COLLECTION_INTERVAL_MIN = 5      # 리소스 수집 주기(cron, 분 단위)
EXPECTED_SAMPLES_7D = int(7 * 24 * 60 / COLLECTION_INTERVAL_MIN)  # 2016
RI_ESTIMATED_DISCOUNT_PCT = 35.0  # AWS RI 1년 No Upfront 기준 대략치(30~40%), decisions/0012에 출처 기록 예정


async def fetch_metrics_by_instance(conn):
    """[9주차 수정] cloud별로 합치지 않고 (cloud, instance_id) 조합마다 각각 반환.
    예전엔 {cloud: dict(row)} 형태로 합치면서, 한 클라우드에 인스턴스가 여러 개면
    마지막 것만 남고 나머지는 조용히 사라지는 버그가 있었음."""
    rows = await conn.fetch("""
        SELECT cloud, instance_id,
               AVG(cpu_avg) AS avg_cpu_7d,
               AVG(memory_avg) AS avg_mem_7d
        FROM resource_metrics
        WHERE source = 'real'
          AND cpu_avg IS NOT NULL
          AND timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY cloud, instance_id
    """)
    return [dict(r) for r in rows]


async def fetch_uptime_by_instance(conn):
    """[10주차] (cloud, instance_id)별 최근 7일 실측 데이터 포인트 수 -> 가동 시간 비율 추정.
    수집 주기가 5분이므로 기대 샘플 수(2016개) 대비 실제 샘플 수 비율로 계산한다."""
    rows = await conn.fetch("""
        SELECT cloud, instance_id, COUNT(*) AS sample_count
        FROM resource_metrics
        WHERE source = 'real'
          AND cpu_avg IS NOT NULL
          AND timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY cloud, instance_id
    """)
    return {(r['cloud'], r['instance_id']): min(r['sample_count'] / EXPECTED_SAMPLES_7D, 1.0) for r in rows}


async def fetch_cost_by_cloud(conn):
    rows = await conn.fetch("""
        SELECT cloud, SUM(cost_usd) AS total_cost_7d
        FROM cost_records
        WHERE date >= (CURRENT_DATE - INTERVAL '7 days')
        GROUP BY cloud
    """)
    return {r['cloud']: r['total_cost_7d'] for r in rows}


def judge(avg_cpu, avg_mem, total_cost):
    # [9주차] CPU와 메모리 둘 다 15% 미만이면서 비용이 발생 중이면 downsize
    # 하나라도 기준 이상이면 keep - CPU만 낮고 메모리를 많이 먹는 인스턴스를
    # 잘못 downsize 추천하지 않기 위함
    # synthetic 인스턴스는 cost_records에 없으므로(실제 비용 없음) 자동 제외됨
    if total_cost is None or total_cost <= 0:
        return 'keep', 'DB에 최근 7일 비용 데이터 없음 - 판단 보류'

    cpu_low = avg_cpu is not None and avg_cpu < CPU_THRESHOLD
    mem_low = avg_mem is not None and avg_mem < MEM_THRESHOLD

    if cpu_low and mem_low:
        return 'downsize', (
            f'최근 7일 평균 CPU {avg_cpu:.1f}%, 메모리 {avg_mem:.1f}%로 둘 다 낮은데 '
            f'비용은 ${total_cost:.2f} 발생 중'
        )

    cpu_str = f'{avg_cpu:.1f}%' if avg_cpu is not None else '데이터 없음'
    mem_str = f'{avg_mem:.1f}%' if avg_mem is not None else '데이터 없음'
    return 'keep', f'최근 7일 평균 CPU {cpu_str}, 메모리 {mem_str} - 정상 범위'


def judge_commitment(uptime_ratio):
    """[10주차] 최근 7일 가동 시간 비율 기준 예약 인스턴스(RI) 전환 추천.
    기존 downsize 로직과 독립적으로 판단 - 둘 다 해당될 수도 있음
    (계속 떠있지만 저활용이라 downsize도, RI도 같이 나올 수 있음)."""
    if uptime_ratio is None:
        return None, None, '가동 시간 데이터 없음'
    if uptime_ratio >= UPTIME_THRESHOLD:
        return (
            'reserved_instance',
            RI_ESTIMATED_DISCOUNT_PCT,
            f'최근 7일 가동 시간 비율 {uptime_ratio*100:.1f}%로 상시 가동에 가까움 - '
            f'RI 전환 시 약 {RI_ESTIMATED_DISCOUNT_PCT:.0f}% 절감 예상',
        )
    return (
        'keep_on_demand',
        None,
        f'최근 7일 가동 시간 비율 {uptime_ratio*100:.1f}%로 상시 가동이 아님 - 온디맨드 유지 권장',
    )


async def generate_recommendations():
    conn = await asyncpg.connect(DATABASE_URL)

    metrics = await fetch_metrics_by_instance(conn)
    cost_by_cloud = await fetch_cost_by_cloud(conn)
    uptime_by_instance = await fetch_uptime_by_instance(conn)  # [10주차]

    if not metrics:
        print("[INFO] 최근 7일 real 데이터 없음")
        await conn.close()
        return

    now = datetime.now(timezone.utc)
    results = []
    for row in metrics:
        cloud = row['cloud']
        instance_id = row['instance_id']
        avg_cpu = row['avg_cpu_7d']
        avg_mem = row['avg_mem_7d']
        total_cost = cost_by_cloud.get(cloud)

        recommendation, reason = judge(avg_cpu, avg_mem, total_cost)

        # [10주차] RI 추천 - 기존 downsize 판단과 별개 컬럼
        uptime_ratio = uptime_by_instance.get((cloud, instance_id))
        commitment_recommendation, estimated_discount_pct, commitment_reason = judge_commitment(uptime_ratio)

        await conn.execute("""
            INSERT INTO recommendations
                (cloud, instance_id, avg_cpu_7d, total_cost_7d, recommendation, reason,
                 commitment_recommendation, estimated_discount_pct, generated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (cloud, instance_id, generated_at) DO NOTHING
        """, cloud, instance_id, avg_cpu, total_cost, recommendation, reason,
             commitment_recommendation, estimated_discount_pct, now)

        results.append((cloud, instance_id, avg_cpu, avg_mem, total_cost, recommendation, commitment_recommendation))
        cpu_str = f"CPU {avg_cpu:.1f}%" if avg_cpu is not None else "CPU 데이터 없음"
        mem_str = f"메모리 {avg_mem:.1f}%" if avg_mem is not None else "메모리 데이터 없음"
        cost_str = f"비용 ${total_cost:.2f}" if total_cost is not None else "비용 데이터 없음"
        print(f"[{cloud}] {instance_id} - {cpu_str} / {mem_str} / {cost_str} -> "
              f"{recommendation} / {commitment_recommendation} ({commitment_reason})")

    print(f"[OK] 추천 {len(results)}건 저장 완료")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(generate_recommendations())
