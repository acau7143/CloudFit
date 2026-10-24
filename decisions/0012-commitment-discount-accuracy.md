# 0012. 클라우드별 약정 할인율 산정 방식 (근사치 → 실측 API 조회)

## Context
Week10에서 `ml/recommend.py`에 클라우드별 약정 할인(AWS/Azure Reserved Instance, GCP
Committed Use Discount) 전환 추천 기능을 추가하면서, `COMMITMENT_INFO` 딕셔너리에
할인율을 하드코딩했다.

```python
COMMITMENT_INFO = {
    'AWS':   {'label': 'reserved_instance', 'discount_pct': 35.0},
    'Azure': {'label': 'reserved_instance', 'discount_pct': 35.0},
    'GCP':   {'label': 'committed_use',     'discount_pct': 37.0},
}
```

이 값들은 "1년 No Upfront 공식 문서상 30~40% 범위의 중간값" 같은 업계 통용
근사치였고, 정식 출처나 대안 비교가 문서화돼 있지 않았다.

문제는 `/recommendations` API가 `"estimated_discount_pct": 37.0`처럼 이 근사치를
그대로 응답에 내보낸다는 점이다. `float` 단일값이라 마치 실측 정밀값처럼 보이는데,
실제로는 근사치라는 게 API 응답만 봐서는 전혀 드러나지 않는다. 통합 검증(Day3)
과정에서 이 문제가 지적됨(성민).

## Decision
근사치를 유지하되 문서에만 한계를 명시하는 방식 대신, **각 클라우드의 공식 가격
조회 API로 이 프로젝트가 실제 사용 중인 인스턴스 종류·리전 기준 실측 할인율을
1회 조회해서 `COMMITMENT_INFO`에 반영**한다.

상시 도는 파이프라인이 아니라 클라우드별 조사용 스크립트(`ml/*_lookup.py`)로 만들고,
각 클라우드 담당자가 자기 인증 정보로 직접 실행한다.

| 클라우드 | 담당 | API | 인증 | 스크립트 |
|---|---|---|---|---|
| GCP | C (성민) | Cloud Billing Catalog API | 서비스 계정 필요 | `ml/gcp_cud_lookup.py` |
| Azure | B | Retail Prices API (prices.azure.com) | 불필요 (완전 공개) | `ml/azure_reservation_lookup.py` |
| AWS | A | Price List API (`boto3.client('pricing')`) | IAM 자격증명 필요 | `ml/aws_ri_lookup.py` |

## Why
- API 응답 구조(단일 `float` 필드)가 "근사치"와 "실측값"을 구분하지 못해서, 근사치를
  그대로 두면 API 소비자(대시보드, 발표 심사위원)가 정밀 실측값으로 오해할 수 있음
- 발표/심사 중 "이 37%는 어떻게 나온 숫자냐"는 질문에 "실제 가격 API로 조회했다"고
  답할 수 있어야 신뢰도가 생김
- 완전 자동화(추천 생성 시마다 실시간 API 호출)는 클라우드당 반나절~하루 소요로
  이번 주(Week10 Day4~5에 README·발표자료·통합테스트가 남아있음) 일정에 부담이 큼
  → "1회 조사 후 하드코딩 교체" 절충안을 채택 (대안 비교 참고)

## 대안과의 비교
| 대안 | 소요 시간(클라우드당) | 비교 |
|---|---|---|
| 근사치 유지 + 문서에 한계만 명시 | 0 (문서화만) | 가장 빠르지만 API 응답이 여전히 부정확한 값을 정밀값처럼 노출하는 문제는 그대로 남음 |
| **1회 API 조회 후 하드코딩 교체 (채택)** | 2~3시간 | 정확도 개선 대비 시간 부담이 적음. 대신 인스턴스 타입/리전이 바뀌면 재조회 필요 |
| 실시간 API 연동(추천 생성 시마다 호출) | 반나절~하루 | 가장 정확하지만 SKU 매칭 로직 견고화·캐싱·에러 처리까지 갖춰야 해서 이번 주 일정에 맞지 않음. README "향후 개선 방향"에 기록해두고 보류 |

## Result
- **GCP**: 조회 진행 중 (`ml/gcp_cud_lookup.py` 실행 결과 반영 예정)
- **Azure**: `Standard_B1s` / `koreacentral` 기준 실측 **35.03%** 확인 (Savings Plan
  값 사용 — B 시리즈는 전통 Reserved VM Instance 미지원이라는 사실을 이번에 처음
  확인함). 단, 이 VM 크기/리전이 실제 `azure_exporter.py` 운영 값인지 재확인 필요
- **AWS**: `t3.micro` / `ap-northeast-2` 기준 실측 **39.23%** 확인 (1yr No Upfront)
- 3개 클라우드 모두 확정되면 `ml/recommend.py`의 `COMMITMENT_INFO`를 갱신하고
  이 Result 섹션도 최종 수치로 업데이트한다

## 담당자별 할 일

### B (Azure) 담당자
1. 실제 VM 크기/리전 확인:
   ```bash
   az vm show --name <vm이름> -g <리소스그룹> --query "[hardwareProfile.vmSize, location]"
   ```
2. 스크립트 실행 (인증 불필요, `pip install requests`만 있으면 됨):
   ```bash
   python3 ml/azure_reservation_lookup.py --vm-size <실제크기> --region <실제리전>
   ```
3. 출력된 할인율을 이 문서 Result 섹션과 `recommend.py`의 `COMMITMENT_INFO['Azure']`에 반영
4. 실행 중 SKU가 하나도 안 나오면: `--vm-size`/`--region` 철자 확인 (Azure 포털 표기와
   `armSkuName`/`armRegionName` 표기가 다를 수 있음 — 예: 화면엔 "Central Korea"인데
   API 파라미터는 `koreacentral`)

### A (AWS) 담당자
1. AWS Price List API는 **`us-east-1` 리전에서만 서비스**된다 (다른 리전으로 클라이언트
   만들면 빈 결과 나옴 — 실제 EC2가 도는 리전과 무관하게 API 호출 자체는 항상 us-east-1)
2. 필요 IAM 권한: `pricing:GetProducts` (읽기 전용)
3. 스크립트(`ml/aws_ri_lookup.py`)는 성민이 이어서 작성해 공유 예정. 급하면 아래 원리로
   직접 조회 가능:
   ```python
   import boto3
   client = boto3.client('pricing', region_name='us-east-1')
   response = client.get_products(
       ServiceCode='AmazonEC2',
       Filters=[
           {'Type': 'TERM_MATCH', 'Field': 'instanceType', 'Value': '<실제 인스턴스 타입>'},
           {'Type': 'TERM_MATCH', 'Field': 'regionCode', 'Value': '<실제 리전>'},
           {'Type': 'TERM_MATCH', 'Field': 'operatingSystem', 'Value': 'Linux'},
           {'Type': 'TERM_MATCH', 'Field': 'tenancy', 'Value': 'Shared'},
           {'Type': 'TERM_MATCH', 'Field': 'preInstalledSw', 'Value': 'NA'},
       ]
   )
   # response['PriceList']의 각 항목(JSON 문자열)에 'terms'.'OnDemand'와
   # 'terms'.'Reserved' 가 같이 들어있음. Reserved 안에서
   # leaseContractLength='1yr', purchaseOption='No Upfront' 조건인 걸 찾아서
   # OnDemand 시간당가와 비교하면 할인율이 나옴.
   ```
4. 결과를 이 문서와 `COMMITMENT_INFO['AWS']`에 반영

막히면 혼자 2시간 이상 붙잡지 말고 팀 채팅에 에러 메시지와 함께 바로 공유할 것
(GUIDELINES.md 3번 공통 규칙).
