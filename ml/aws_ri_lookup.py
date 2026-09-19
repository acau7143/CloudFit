"""
AWS Price List API로 실측 Reserved Instance(RI) 할인율을 조회한다. (decisions/0012)

- Price List API는 리전과 무관하게 항상 us-east-1에서만 서비스된다
  (조회 대상 인스턴스가 어느 리전에서 도는지와는 별개).
- 필요 IAM 권한: pricing:GetProducts (읽기 전용)
  -> runbook 기준 finops-collector 사용자에 ReadOnlyAccess가 붙어있어서
     별도 권한 신청 없이 바로 동작할 가능성이 높다.
- '1yr / No Upfront' 조건으로 On-Demand 대비 할인율을 계산한다.

사용 예 (프로젝트 테스트 인스턴스 기준 - 기본값으로 이미 들어있음):
    python3 ml/aws_ri_lookup.py
    python3 ml/aws_ri_lookup.py --instance-type t3.micro --region ap-northeast-2
"""
import argparse
import json

import boto3

# decisions/0012 Result 섹션에 반영할 조건 (No Upfront 고정 - AWS/Azure 방식 통일)
LEASE_CONTRACT_LENGTH = "1yr"
PURCHASE_OPTION = "No Upfront"


def fetch_price_list(instance_type: str, region: str, os_name: str = "Linux"):
    # Price List API는 항상 us-east-1에서만 서비스된다 (조회 리전 != 대상 인스턴스 리전)
    client = boto3.client("pricing", region_name="us-east-1")

    resp = client.get_products(
        ServiceCode="AmazonEC2",
        Filters=[
            {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
            {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
            {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": os_name},
            {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
            {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        ],
    )
    return [json.loads(item) for item in resp.get("PriceList", [])]


def extract_ondemand_hourly(product: dict):
    for term in product["terms"].get("OnDemand", {}).values():
        for dim in term["priceDimensions"].values():
            price = float(dim["pricePerUnit"]["USD"])
            if price > 0:
                return price
    return None


def extract_reserved_hourly(product: dict):
    """leaseContractLength=1yr, purchaseOption=No Upfront 조건에 맞는 시간당 요금."""
    for term in product["terms"].get("Reserved", {}).values():
        attrs = term["termAttributes"]
        if (
            attrs.get("LeaseContractLength") == LEASE_CONTRACT_LENGTH
            and attrs.get("PurchaseOption") == PURCHASE_OPTION
        ):
            for dim in term["priceDimensions"].values():
                if dim.get("unit") == "Hrs":
                    return float(dim["pricePerUnit"]["USD"])
    return None


def lookup(instance_type: str, region: str, os_name: str = "Linux"):
    products = fetch_price_list(instance_type, region, os_name)

    if not products:
        print(f"[경고] 조건에 맞는 상품이 없음 (instanceType={instance_type}, "
              f"regionCode={region}, os={os_name}) - 필터 값 재확인 필요")
        return

    results = []
    for product in products:
        ondemand = extract_ondemand_hourly(product)
        reserved = extract_reserved_hourly(product)
        if ondemand and reserved:
            discount_pct = (ondemand - reserved) / ondemand * 100
            results.append((ondemand, reserved, discount_pct))

    if not results:
        print(f"[경고] {len(products)}개 상품 조회는 됐는데 "
              f"{LEASE_CONTRACT_LENGTH}/{PURCHASE_OPTION} 조건의 Reserved 가격을 못 찾음")
        return

    if len(results) > 1:
        print(f"[주의] 조건에 맞는 상품이 {len(results)}개 나옴 - 첫 번째 결과로 계산 "
              f"(전부 동일 값인지 아래에서 직접 확인할 것)")
        for od, rv, pct in results:
            print(f"  - OnDemand ${od:.4f}/h, Reserved(No Upfront) ${rv:.4f}/h, 할인율 {pct:.2f}%")

    ondemand, reserved, discount_pct = results[0]

    print(f"\n[{instance_type} / {region} / {os_name}] {LEASE_CONTRACT_LENGTH} {PURCHASE_OPTION} 기준")
    print(f"  On-Demand:  ${ondemand:.4f} / 시간")
    print(f"  Reserved:   ${reserved:.4f} / 시간")
    print(f"  할인율:      {discount_pct:.2f}%")

    print("\n--- COMMITMENT_INFO['AWS'] 갱신용 (ml/recommend.py) ---")
    print(f"    'AWS':   {{'label': 'reserved_instance', 'discount_pct': {discount_pct:.2f}}},")

    print("\n--- decisions/0012 Result 섹션 갱신용 문구 ---")
    print(f"- **AWS**: `{instance_type}` / `{region}` 기준 실측 **{discount_pct:.2f}%** 확인 "
          f"({LEASE_CONTRACT_LENGTH} {PURCHASE_OPTION})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AWS RI 실측 할인율 조회 (decisions/0012)")
    # 기본값은 runbook/aws-collector-setup.md의 테스트 인스턴스 스펙
    parser.add_argument("--instance-type", default="t3.micro")
    parser.add_argument("--region", default="ap-northeast-2")
    parser.add_argument("--os", default="Linux", help="operatingSystem 필터값 (기본 Linux)")
    args = parser.parse_args()

    lookup(args.instance_type, args.region, args.os)
