#!/usr/bin/env python3
"""
설치 후 사전 점검 (decisions/0015 단계 2).

새 환경에서 수집기/서버를 켜기 전에 "무엇이 아직 안 돼 있는지"를 항목별로 알려준다.
서버로 데이터를 전송하거나 DB를 바꾸지 않고 조회만 한다.

    python scripts/check_prereqs.py <aws|gcp|azure|server>

종료 코드: [FAIL] 이 하나라도 있으면 1, 없으면 0 ([WARN] 은 동작은 하지만 데이터가 비는 항목).
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _path in (ROOT, ROOT / "collectors"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import cloud_config  # noqa: E402  (collectors/cloud_config.py)

OK, WARN, FAIL = "OK", "WARN", "FAIL"


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------

def _safe(name, func):
    """점검 하나를 실행한다. 예외가 나면 FAIL 로 바꿔서 나머지 점검이 계속되게 한다."""
    try:
        return func()
    except ImportError as e:
        return (FAIL, name, f"패키지가 설치돼 있지 않습니다: {e}")
    except Exception as e:  # 권한/네트워크/설정 오류를 점검 결과로 보여주기 위함
        return (FAIL, name, f"{type(e).__name__}: {str(e)[:200]}")


def check_env(name, keys):
    missing = [k for k in keys if not cloud_config.get_env(k)]
    if missing:
        return (FAIL, name, ".env 에 빠진 키: " + ", ".join(missing))
    return (OK, name, f"{len(keys)}개 키 확인")


def check_server_health(name="서버 연결 (SERVER_URL)"):
    import requests
    url = cloud_config.get_env("SERVER_URL", "http://localhost:8000")
    try:
        r = requests.get(f"{url}/health", timeout=5)
    except requests.RequestException as e:
        return (FAIL, name, f"{url} 에 접속할 수 없습니다 ({type(e).__name__}). 서버 기동, 포트 8000 방화벽, SERVER_URL 확인")
    if r.status_code != 200:
        return (FAIL, name, f"{url}/health 가 {r.status_code} 를 반환했습니다")
    return (OK, name, f"{url}/health 정상")


def metric_results(cpu, memory, disk, hints):
    """CPU 는 필수(FAIL), 메모리/디스크는 에이전트가 필요해서 비어 있으면 WARN."""
    results = []
    if cpu is None:
        results.append((FAIL, "CPU 지표", hints["cpu"]))
    else:
        results.append((OK, "CPU 지표", f"{cpu}%"))
    for label, value, key in (("메모리 지표", memory, "memory"), ("디스크 지표", disk, "disk")):
        if value is None:
            results.append((WARN, label, hints[key]))
        else:
            results.append((OK, label, f"{value}%"))
    return results


# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------

def _boto3_client(service, region):
    import boto3
    return boto3.client(service, region_name=region)


def aws_checks():
    results = []
    env = check_env("AWS 설정 (.env)", ["AWS_REGION", "AWS_INSTANCE_ID"])
    results.append(env)
    if env[0] == FAIL:
        return results
    region = cloud_config.aws_region()
    instance_id = cloud_config.aws_instance_id()

    def identity():
        _boto3_client("sts", region).get_caller_identity()
        return (OK, "AWS 자격증명", "유효 (EC2 인스턴스 역할 또는 로컬 자격증명)")
    ident = _safe("AWS 자격증명", identity)
    results.append(ident)
    if ident[0] == FAIL:
        results.append((FAIL, "AWS 자격증명 안내", "EC2 에 IAM 역할을 연결했는지 확인 (runbook/new-environment-setup.md 권한 표)"))
        return results

    import aws_exporter  # noqa: E402

    def instance():
        itype = aws_exporter.get_instance_type(instance_id)
        return (OK, "대상 인스턴스 조회", f"{instance_id} ({itype})")
    results.append(_safe("대상 인스턴스 조회", instance))

    def metrics():
        cpu, memory, disk = aws_exporter.collect_resource_metrics(instance_id)
        return metric_results(cpu, memory, disk, {
            "cpu": "CPU 데이터 없음: 인스턴스가 꺼져 있거나 생성 직후(5~10분)일 수 있음",
            "memory": "메모리 데이터 없음: CloudWatch Agent 설치/시작 확인 (적용 후 최대 10~20분 지연)",
            "disk": "디스크 데이터 없음: aws cloudwatch list-metrics --namespace CWAgent 로 device/fstype 확인 후 "
                    ".env 의 AWS_DISK_DEVICE / AWS_DISK_FSTYPE 조정",
        })
    m = _safe("자원 지표 조회", metrics)
    results.extend(m if isinstance(m, list) else [m])

    def cost():
        from datetime import datetime, timedelta, timezone
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=2)
        _boto3_client("ce", "us-east-1").get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="DAILY", Metrics=["UnblendedCost"],
        )
        return (OK, "비용 조회 (Cost Explorer)", "조회 가능")
    c = _safe("비용 조회 (Cost Explorer)", cost)
    if c[0] == FAIL:  # 비용이 안 돼도 자원 수집은 되므로 경고로 낮춘다
        c = (WARN, c[1], "조회 불가 - ce:GetCostAndUsage 권한 또는 Cost Explorer 활성화(최초 활성화 후 최대 24시간) 확인. " + c[2])
    results.append(c)

    results.append(_safe("서버 연결 (SERVER_URL)", check_server_health))
    return results


# ---------------------------------------------------------------------------
# GCP
# ---------------------------------------------------------------------------

def gcp_checks():
    results = []
    env = check_env("GCP 설정 (.env)", [
        "GCP_PROJECT_ID", "GCP_ZONE", "GCP_INSTANCE_NAME", "GCP_BILLING_ACCOUNT_ID",
    ])
    results.append(env)
    if env[0] == FAIL:
        return results
    project = cloud_config.gcp_project_id()
    zone = cloud_config.gcp_zone()
    name = cloud_config.gcp_instance_name()
    billing = cloud_config.gcp_billing_account_id()

    def adc():
        import google.auth
        google.auth.default()
        return (OK, "GCP 자격증명 (ADC)", "VM 서비스 계정 또는 로컬 자격증명 확인")
    a = _safe("GCP 자격증명 (ADC)", adc)
    results.append(a)
    if a[0] == FAIL:
        return results

    import gcp_exporter  # noqa: E402

    target = {}

    def instance():
        info = gcp_exporter.get_instance(project, zone, name)
        target["id"] = str(info["id"])
        return (OK, "대상 인스턴스 조회", f"{name} ({info['machineType'].split('/')[-1]})")
    results.append(_safe("대상 인스턴스 조회", instance))

    def metrics():
        # 수집기와 같이 대상 VM 의 지표만 조회한다 (프로젝트에 VM 이 여러 대여도 섞이지 않게)
        cpu = gcp_exporter.collect_cpu(project, instance_id=target.get("id"))
        memory = gcp_exporter.collect_memory(project, instance_id=target.get("id"))
        disk = gcp_exporter.collect_disk(project, instance_id=target.get("id"))
        return metric_results(
            gcp_exporter._average(cpu, "cpu_percent"),
            gcp_exporter._average(memory, "memory_percent"),
            gcp_exporter._average(disk, "disk_percent"),
            {
                "cpu": "CPU 데이터 없음: 인스턴스가 꺼져 있거나 monitoring.viewer 권한/프로젝트 ID 확인",
                "memory": "메모리 데이터 없음: Ops Agent 설치/시작과 VM 서비스 계정의 monitoring.metricWriter 권한 확인",
                "disk": "디스크 데이터 없음: Ops Agent 확인, device 라벨이 다르면 .env 의 GCP_DISK_DEVICE 조정",
            },
        )
    m = _safe("자원 지표 조회", metrics)
    results.extend(m if isinstance(m, list) else [m])

    def billing_export():
        from google.cloud import bigquery
        table = f"{project}.billing_export.gcp_billing_export_v1_{billing.replace('-', '_')}"
        bigquery.Client(project=project).get_table(table)
        return (OK, "비용 조회 (BigQuery billing export)", "내보내기 테이블 확인")
    b = _safe("비용 조회 (BigQuery billing export)", billing_export)
    if b[0] == FAIL:  # 없으면 수집기가 추정치로 대체하므로 경고로 낮춘다
        b = (WARN, b[1], "내보내기 테이블 없음 - billing export 를 켜고(켠 시점부터만 쌓임) bigquery 권한 확인. "
                         "그동안 비용은 추정치로 대체됨. " + b[2])
    results.append(b)

    results.append(_safe("서버 연결 (SERVER_URL)", check_server_health))
    return results


# ---------------------------------------------------------------------------
# Azure
# ---------------------------------------------------------------------------

AZURE_KEYS = [
    "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "AZURE_SUBSCRIPTION_ID",
    "AZURE_RESOURCE_GROUP", "AZURE_VM_NAME", "AZURE_LOG_WORKSPACE_ID",
]


def azure_checks():
    results = []
    env = check_env("Azure 설정 (.env)", AZURE_KEYS)
    results.append(env)
    if env[0] == FAIL:
        return results

    import azure_exporter  # noqa: E402

    def token():
        config = azure_exporter.load_config()
        azure_exporter.build_credential(config).get_token("https://management.azure.com/.default")
        return (OK, "Azure 서비스 프린시펄 인증", "토큰 발급 성공")
    t = _safe("Azure 서비스 프린시펄 인증", token)
    results.append(t)
    if t[0] == FAIL:
        return results

    def metrics():
        raw = azure_exporter.collect_resource_metrics()
        return metric_results(raw["cpu_avg"], raw["memory_avg"], raw["disk_avg"], {
            "cpu": "CPU 데이터 없음: VM 이름/리소스 그룹 확인, VM 이 꺼져 있지 않은지, Monitoring Reader 권한 확인",
            "memory": "메모리 데이터 없음: Azure Monitor Agent, 데이터 수집 규칙(DCR), Log Analytics 연결과 "
                      "Log Analytics Reader 권한 확인",
            "disk": "디스크 데이터 없음: 루트(/) Perf 데이터가 Log Analytics 로 들어오는지 확인",
        })
    m = _safe("자원 지표 조회", metrics)
    results.extend(m if isinstance(m, list) else [m])

    # 비용 조회(Cost Management)는 호출 한도(429)가 빡빡해서 점검에서는 호출하지 않는다 (incidents/INC-001).
    results.append((WARN, "비용 조회 (Cost Management)",
                    "점검에서는 호출하지 않음(429 한도). Cost Management Reader 권한은 수집기를 한 번 실행해서 확인"))
    results.append(_safe("서버 연결 (SERVER_URL)", check_server_health))
    return results


# ---------------------------------------------------------------------------
# 서버
# ---------------------------------------------------------------------------

SERVER_TABLES = [
    "resource_metrics", "cost_records", "anomaly_results",
    "recommendations", "unused_resources", "allocation_rules",
]


def server_checks():
    results = []
    env = check_env("서버 설정 (.env)", ["DB_PASSWORD", "DATABASE_URL"])
    results.append(env)
    results.append(_safe("서버 API (localhost)", lambda: _local_health()))

    if env[0] == FAIL:
        return results

    def db():
        import asyncio
        import asyncpg

        async def run():
            conn = await asyncpg.connect(cloud_config.get_env("DATABASE_URL"), timeout=10)
            try:
                missing = []
                for table in SERVER_TABLES:
                    if await conn.fetchval("SELECT to_regclass($1)", f"public.{table}") is None:
                        missing.append(table)
                return missing
            finally:
                await conn.close()

        missing = asyncio.run(run())
        if missing:
            return (FAIL, "DB 테이블", "없는 테이블: " + ", ".join(missing)
                    + " (db/schema.sql 은 볼륨이 비어 있는 최초 기동에만 실행됨 - runbook/server-setup.md 4번)")
        return (OK, "DB 테이블", f"{len(SERVER_TABLES)}개 확인")
    results.append(_safe("DB 테이블", db))
    return results


def _local_health():
    import requests
    url = "http://localhost:8000"
    try:
        r = requests.get(f"{url}/health", timeout=5)
    except requests.RequestException as e:
        return (FAIL, "서버 API (localhost)", f"{url}/health 접속 실패 ({type(e).__name__}). docker compose 상태 확인")
    if r.status_code != 200:
        return (FAIL, "서버 API (localhost)", f"{url}/health 가 {r.status_code} 를 반환했습니다")
    return (OK, "서버 API (localhost)", f"{url}/health 정상")


# ---------------------------------------------------------------------------

CHECKS = {"aws": aws_checks, "gcp": gcp_checks, "azure": azure_checks, "server": server_checks}


def exit_code(results):
    return 1 if any(status == FAIL for status, _, _ in results) else 0


def print_results(cloud, results):
    print(f"=== 사전 점검: {cloud} ===")
    for status, name, detail in results:
        print(f"[{status:<4}] {name}" + (f" - {detail}" if detail else ""))
    counts = {s: sum(1 for r in results if r[0] == s) for s in (OK, WARN, FAIL)}
    print(f"--- OK {counts[OK]} / WARN {counts[WARN]} / FAIL {counts[FAIL]}")
    if counts[FAIL]:
        print("[FAIL] 항목을 해결한 뒤 다시 실행하세요.")
    elif counts[WARN]:
        print("[WARN] 은 동작은 하지만 해당 데이터가 비게 됩니다. 필요하면 안내대로 조치하세요.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="CloudFit 설치 사전 점검")
    parser.add_argument("cloud", choices=sorted(CHECKS))
    args = parser.parse_args(argv)
    results = CHECKS[args.cloud]()
    print_results(args.cloud, results)
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
