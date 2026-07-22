# Ⅲ장 집필용 코드 참조 가이드 (산출물 4)

`3. 김현수(0719)_다시 구상.hwpx`에서 정리한 "권장 최종 목차"(Ⅲ. I2M 시스템 설계 및 구현)를
실제로 집필할 때, 각 절·항목마다 어떤 코드 파일·함수를 근거로 서술하면 되는지 정리한
문서다. `docs/INTEGRATION_SURVEY.md`(폴더 단위 조사)·`docs/INTEGRATION_PRINCIPLES.md`
(병합 원칙)와 내용은 같은 코드베이스를 가리키지만, 이 문서는 **목차 항목 순서**로
재조직했다는 점이 다르다. 코드 전문은 옮기지 않았으니, 서술에 인용할 코드를 열어볼 때는
아래 경로를 직접 열어서 확인할 것.

## 구현 상태 범례

집필 시 가장 조심해야 할 부분이다. 아래 세 상태를 항목마다 반드시 구분해서 쓸 것
(hwpx 메모의 "056을 완성된 것처럼 쓰지 말라"는 지적과 같은 원칙을 전체 절에 적용한 것).

| 표시 | 의미 |
|---|---|
| ✅ 실동작 | `i2m_kormarc/`에 이관되어 실제로 호출되는 코드. `app.py`의 `_run_conversion()`이 직접 실행한다. |
| 🚧 스텁 | `core/fields/`에 함수 껍데기(`raise NotImplementedError`)만 있고, 원본 로직은 구 폴더에만 있음. `app.py`가 아직 호출하지 않는다. (041/245/653/260+300 4개 폴더는 모두 이관 완료라 현재 이 상태에 해당하는 필드가 없다 — 예시로만 남겨둔 표시.) |
| ❌ 코드 없음 | 이 통합 코드 전체를 통틀어 어떤 형태로도 구현되어 있지 않음. |

---

## Ⅲ.1 시스템 개요

### 가. 시스템의 목적과 이용 절차

- `i2m_kormarc/app.py` 상단 docstring — 엔드포인트 목록(`POST /api/convert`,
  `POST /api/convert/batch`, `GET /api/kpipa/{isbn}`, `POST /api/feedback`,
  `GET /health`)과 "ISBN 입력 → MARC 변환" 흐름 요약이 이미 문장 형태로 있어 그대로
  참고 가능.
- `i2m_kormarc/pages/1_ISBN_변환.py` — 사서가 실제로 ISBN을 입력해서 결과를 받는 화면.
  "이용 절차"를 그림/흐름도로 그릴 때 이 파일의 입력→호출→결과표시 순서를 따라가면 됨.
- 상태: ✅ 실동작.

### 나. 프론트엔드와 백엔드의 구성

- 프론트엔드: `streamlit_app.py`(상태 대시보드) + `pages/1_ISBN_변환.py`(변환 UI, 단건/일괄).
- 연결: `api_client.py` — 프론트가 백엔드 FastAPI를 호출하는 HTTP 클라이언트.
- 백엔드: `app.py` — FastAPI 오케스트레이터. `lifespan()`에서 시크릿 로드(`core.config.load_streamlit_secrets_into_env`)와 DB 초기화(`database.feedback_logger.init_db`)를 수행.
- 상태: ✅ 실동작. (원 245/653 폴더는 Flask/FastAPI+Streamlit이 각자 따로 있었는데, 통합 후 프론트는 Streamlit 하나, 백엔드는 FastAPI 하나로 일원화됐다는 점을 "신I2M 변경점"으로 쓸 수 있음.)

### 다. 백엔드 모듈 및 통합 코드 구조

`README.md`의 디렉토리 구조 절과 `docs/INTEGRATION_SURVEY.md`의 파일트리를 요약하면:

```
i2m_kormarc/
├── app.py              # FastAPI 오케스트레이터
├── streamlit_app.py, pages/, api_client.py   # 프론트 + 연결
├── core/
│   ├── config.py        # pydantic-settings 통합 설정
│   ├── debug_log.py      # 필드 공용 디버그 로거
│   ├── marc_builder.py    # pymarc.Record ↔ MRK 변환
│   ├── text_utils.py      # 텍스트/이름 정규화 공용 유틸
│   ├── fields/            # 필드별 생성 모듈 (마크 태그 1개~n개 담당)
│   └── name_data/          # 이름판별 참조 데이터
├── api/                 # 외부 API·크롤링 연동 모듈
├── database/             # feedback_logger.py (SQLite)
└── docs/                # 조사/원칙/집필가이드 문서
```

- "백엔드 모듈 구조"는 이 트리 하나로 설명 가능. "통합 코드 구조"라고 쓸 때는
  `통합_계획.md`(041/245/653/260+300 4개 원본 폴더를 이 구조로 합쳤다는 배경)를 함께
  인용하면 신I2M 서술의 핵심 근거가 됨.
- 상태: ✅ 실동작 (구조 자체가 곧 실제 코드).

### 라. 필드별 처리 방식의 개요 (표)

`docs/INTEGRATION_SURVEY.md`의 "필드 담당 매트릭스"를 처리방식 컬럼과 구현상태 컬럼을
더해 확장한 표. 이 표를 그대로 손봐서 논문에 넣으면 된다(hwpx 메모가 "지금 작성한
표를 수정해 넣으면 된다"고 지시한 바로 그 표).

| MARC 필드 | 의미 | 담당 코드 | 처리 방식 | 구현 상태 |
|---|---|---|---|---|
| 245/246/900/940 | 표제·원서명·원저자 한글명 | `core/fields/marc_245.py` | 외부 API·웹 크롤링·규칙·AI | ✅ |
| 500/700/710 | 원저자 주기·개인명/기관명 부출 | `core/fields/marc_500_700_710.py` | 외부 API·규칙·AI(이름 순서 판정) | ✅ |
| 041/546 | 언어코드·언어주기 | `core/fields/marc_041.py`(원본 `041/041.py`) | 규칙·AI 혼합 | ✅ |
| 260 | 발행사항 | `core/fields/marc_260.py` | 외부 API·발행처 DB·규칙 | ✅ |
| 300 | 형태사항 | `core/fields/marc_300.py` | 외부 API·웹 크롤링·규칙·AI($b 삽화 판정) | ✅ |
| 653 | 자유주제어 | `core/fields/marc_653.py`(원본 `653/backend/app/ai_service.py`) | 분야별 프롬프트 기반 생성형 AI + 규칙 후처리 | ✅ |
| 056 | KDC 분류기호 | 없음 | 학습 기반(예정) | ❌ 코드 없음 |

---

## Ⅲ.2 데이터 수집 및 관리 구조

### 가. 외부 Open API를 통한 서지정보 수집

- `api/aladin_client.py` — `get_aladin_item_by_isbn(isbn, secrets)`.
  `OPT_RESULT_FULL` 상수(원 041/245/653/260+300 4개 폴더가 각자 요청하던 옵션의 합집합:
  `authors,subInfo,seriesInfo,Toc,fulldescription,ebookList,usedList,reviewList,fileFormatList,packing,subbarcode`)로 고정 호출.
- `api/kpipa_client.py` — `get_kpipa_book_detail(isbn, api_key)`, `extract_kpipa_publisher_name()`.
- `api/mois_client.py` — `get_mois_publisher_address(publisher_name, api_key)`(행정안전부 발행처 주소).
- `api/nlk_client.py` — 국립중앙도서관 OpenAPI/Seoji 연동(원표제·원저자명 보완용).
  `fetch_kdc_content_code_by_isbn()`은 653이 카테고리를 "기타"/"인문학" 캐치올로밖에
  못 정했을 때만 쓰는 보조 신호(ISBN 부가기호 마지막 3자리)를 Seoji API로 조회 —
  분류기호를 직접 생성하는 것과는 다른, 라우팅 보정용이다. 원본처럼 기본 비활성
  (`core.config.Settings.nlk_enable_653=False`, opt-in).
- 상태: ✅ 실동작 (nlk_client의 KDC 조회 함수 포함).

### 나. 웹 크롤링을 통한 누락 정보 보완

- `api/aladin_scraper.py`(1073줄) — 원 `041/041.py`의 `AladinAuthorScraper`와 원
  `245/245/app.py`의 `scrape_aladin_product()`를 하나로 합친 자리.
  핵심 함수: `scrape_aladin_product(item_id, orig_title_hint=None)`(상품 상세페이지 →
  책소개/목차/원표제/저자정보/쪽수·크기), `gpt_orig_info_lookup(...)`(웹 크롤링으로도
  못 찾은 원제/원저자를 GPT 웹검색으로 보완), 저자 개요 페이지 파싱 계열 함수
  (`_fetch_author_overview_name_cell`, `parse_intro_author_persons` 등).
- 상태: ✅ 실동작. ("API와 크롤링을 병행하는 이유"를 쓸 때 이 파일이 두 원본의 크롤링
  로직을 어떻게 하나로 합쳤는지가 좋은 예시가 됨.)

### 다. 내부 데이터베이스 및 학습데이터 구성

hwpx 메모가 지적한 대로 "참조 DB / 학습데이터 / 평가데이터"를 구분해서 쓸 것.

- **참조 DB(정해진 값 조회·매칭)**:
  - `api/publisher_db.py` — 발행처–발행지 연결 DB, `build_pub_location_bundle()`이
    조회에 사용.
  - `core/name_data/`(`korean_surnames.py`, `korean_given_names.py`,
    `korean_real_name_allowlist.py`, `japanese_surnames.py`, `data/korean_given_name_weights.tsv`)
    — 한국/일본 성씨 및 한국 이름(실명·필명) 판별 데이터. 원 `245` 폴더의 고유 자산이
    통합 코드로 그대로 이관됨.
  - `database/feedback_logger.py` — 사서가 수정한 값을 SQLite에 저장(`field_tag` 컬럼).
    학습데이터가 아니라 **사서 검수 이력 DB**로 분류해서 서술할 것.
- **학습데이터(few-shot 예시)**: 653의 `core/fields/few_shots_653.json`(분야별 few-shot
  예시, 원본 `653/backend/app/few_shots.json`을 그대로 이관)이 GPT 프롬프트에 카테고리별
  "사서가 실제로 붙인 좋은/나쁜 키워드" 예시를 주입하는 데 쓰인다.
- **056 학습데이터**: ❌ 존재하지 않음. 마련된 파일도, 수집 계획 코드도 없음 — Ⅲ.3-마
  절에서 다시 다루되, 이 절에서는 "아직 없다"는 사실만 짧게 언급하는 것으로 충분.
- 상태: 참조 DB(퍼블리셔/이름판별)·few_shots_653.json 모두 ✅ 실동작, 056 학습데이터는 ❌.

### 라. 수집 데이터의 통합과 정규화

- `api/aladin_client.OPT_RESULT_FULL` — "필드별로 다른 알라딘 옵션을 요청하던 문제"를
  옵션 합집합으로 해소한 부분(신I2M의 핵심 변화, `docs/INTEGRATION_PRINCIPLES.md` P1 근거
  그대로 인용 가능).
- `core/text_utils.py` — `parse_authors()`, `to_isbn13()`, `korean_name_reverse()`,
  `english_name_reverse()` 등 여러 필드 모듈이 공유하는 정규화 유틸(245 계열 전용이 아니라
  leaf 모듈로 분리되어 순환참조 없이 재사용됨).
- 상태: ✅ 실동작.

---

## Ⅲ.3 데이터 처리 및 필드 생성 과정

### 가. 공통 전처리 및 정보원 우선순위 적용

- `api/publisher_db.build_pub_location_bundle(isbn, publisher_name_raw, secrets)` —
  발행지 판정을 위한 5단계 우선순위 체인(Chain of Responsibility), 결과 dict의
  `source` 키로 어느 단계에서 확정됐는지 태깅. "정보원 우선순위 적용"을 코드로 보여줄
  때 가장 적합한 예시.
- `core/text_utils.py`의 정규화 함수들 — 특정 필드가 아니라 여러 필드 생성 전에
  공통으로 거치는 전처리 단계로 서술 가능.
- 상태: ✅ 실동작.

### 나. 규칙 기반 처리

- `core/fields/marc_260.py`(`build_260_field`) — 발행처명 정규화·발행지 DB 매칭 등
  명확한 규칙 위주.
- `core/name_data/` 매칭 로직을 사용하는 `marc_245.py`/`marc_500_700_710.py` 내부의
  이름판별 규칙 부분(성씨 사전 조회 등, AI 호출 이전 단계).
- 상태: ✅ 실동작.

### 다. 규칙–생성형 AI 혼합 처리

- `core/fields/marc_300.py` — `$b` 삽화류 판정에 `gpt-4o-mini` +
  `response_format={"type":"json_object"}`로 JSON 강제 응답(183~188행 부근). 규칙으로
  1차 판정 후 애매한 경우만 AI 호출하는 구조.
- `core/fields/marc_500_700_710.py` — `decide_name_order_via_llm()`/
  `_decide_name_order_via_llm_cached()`(142~190행): 한글 음역 외국인 이름의 성·이름
  순서를 규칙으로 못 정하면 GPT로 판별, 결과를 캐싱.
- `core/fields/marc_041.py` — `LangFieldBuilder.determine_h_language()`가 본문
  언어($a)·원서 언어($h)를 판정하는 규칙–AI 혼합 파이프라인의 가장 정교한 예시다:
  유니코드 문자체계 규칙 판정 → 카테고리 힌트 → 경량 GPT(원제 언어만 판별) →
  알라딘 저자/역자 소개글 크롤링(`api.aladin_scraper.AladinAuthorScraper`) + GPT
  종합판정(JSON payload) → 규칙 기반 최종 폴백 순으로, "AI 호출을 최소화하고 규칙으로
  먼저 확정을 시도한다"는 신I2M의 설계 의도를 보여주는 절에 가장 적합하다.
- 상태: 041/300/500·700·710 모두 ✅ 실동작.

### 라. 생성형 AI 기반 주제명 생성 (653)

- ✅ 실동작. `i2m_kormarc/core/fields/marc_653.py`가 구 폴더 `653/backend/app/ai_service.py`
  (1239줄)를 이식한 것으로, `app.py`의 `_run_conversion()`이 041/245/260/300과 함께
  직접 호출한다(`build_653_field()`).
- 핵심 구조는 원본과 동일하게 유지됐다: `CATEGORY_PROMPTS`(18개 분야별 프롬프트),
  `get_category_group()`(카테고리 문자열 → 대분류, "기타"/"인문학" 캐치올일 때만
  ISBN 부가기호로 보정), `_finalize_653()`(①AI 원출력 필터링 → ②텍스트 토크나이즈
  백업[문학 제외] → ③카테고리 기반 대체어, 3단 폴백). hwpx 메모가 제안한 "분야 판별 →
  분야별 프롬프트 적용 → 주제명 후보 생성 → 규칙 기반 후처리 → 부족한 결과 보정 →
  최종 653 조립" 흐름이 정확히 이 파일의 구조와 일치한다.
- 이식하며 원본과 달라진 점(신I2M 변경점으로 서술 가능):
  - OpenAI 호출은 원본처럼 Responses API(`client.responses.create`, `instructions`
    파라미터)를 그대로 쓰되, `AsyncOpenAI` 대신 동기 `openai.OpenAI` 클라이언트로
    바꿔 `app.py` 전체를 비동기로 전환하지 않고도 041/245/260/300과 같은 방식으로
    순차 호출되게 했다(`_call_static_instructions_api()`).
  - 알라딘 "출판사 제공 책소개" 크롤링(`getContents.aspx`)은 원본의 `httpx` 비동기
    버전을 `requests` 동기 버전으로 바꿔 `api/aladin_scraper.py`에 이식
    (`crawl_aladin_publisher_intro_and_toc()`).
  - KPIPA ONIX 목차 추출(`api/kpipa_client.extract_kpipa_toc_only()`)과 NLK 부가기호
    조회(`api/nlk_client.fetch_kdc_content_code_by_isbn()`)는 원본처럼 기본 비활성
    (opt-in)으로 유지했다.
  - 원본의 ISBN 결과 TTL 캐시와 Google Sheets "골든데이터" 저장은 이식하지 않았다 —
    전자는 다른 필드 모듈과의 아키텍처 일관성이 깨지고, 후자는 이미 범용적인
    `database/feedback_logger.py`(POST `/api/feedback`)가 동일한 역할을 하기 때문이다.
- 실제 검증 예: 한강 『채식주의자』(문학) → `심리소설`·`트라우마`·`정체성혼란`·
  `생명윤리` 등 키워드 정상 생성(GPT+규칙 후처리 실측).

### 마. 학습 기반 분류기호 생성 (056)

- ❌ 코드 없음. 통합 코드(`i2m_kormarc`) 뿐 아니라 원본 4개 폴더(041/245/653/260+300)
  어디에도 056/KDC 분류를 학습·추론하는 모델 코드, 학습데이터, 평가 스크립트가 전혀
  없다. `api/nlk_client.fetch_kdc_content_code_by_isbn()`은 이제 구현되어 있지만
  (Ⅲ.2-가 참고), 이는 학습 모델이 아니라 Seoji API에서 기존 KDC 부가기호를 그대로
  조회해 653 판별에 힌트로 쓰는 용도다(분류기호를 직접 생성·추론하는 것과는 다른
  목적 — 이 함수의 존재를 056 구현의 근거로 인용하지 말 것).
- hwpx 메모 자신도 이 절을 "개발과 평가 완료 / 모델은 구현됐으나 평가 중 / 아직
  개발 중"세 상태로 나눠 쓰라고 명시했는데, 현재 코드 기준으로는 **셋 중 어디에도
  해당하지 않는 "미착수" 상태**에 가깝다. 따라서 메모의 권고를 그대로 따르면, 이 절은
  Ⅲ장에서 완성된 시스템 구성요소로 서술하지 말고 연구 방법·향후 구현 항목으로
  한정해서 쓰는 것이 코드 현황과 맞다.

### 바. 필드 간 연계 및 KORMARC 레코드 조립·출력

- `core/marc_builder.py` — `MarcBuilder` 클래스(pymarc.Record 래퍼),
  `kormarc_tag_to_mrk(raw)`(태그 표기를 표준 MRK 형식으로 정규화),
  `mrk_str_to_field(line)`(MRK 문자열 → `pymarc.Field`), `record_to_mrk(rec)`.
- `app.py`의 `_run_conversion()` 내부 `_add()` 헬퍼(196~208행) — 245 계열과 260/300
  계열이 서로 다른 태그 표기 관용을 쓰는 것을 흡수해 하나의 MRK 텍스트로 합치고,
  동시에 `builder.rec.add_field()`로 바이너리 MARC 레코드에도 반영. "필드 간 연계"를
  코드로 보여줄 때 이 함수가 가장 직접적인 예시(245의 `orig_title`을 041/500이 참고하는
  구조 등도 `f245_ctx` dict 전달 방식으로 여기서 확인 가능).
- 상태: ✅ 실동작. 041/546/245/246/500/700/710/900/940/260/300/653 전 필드가
  `_add()`를 거쳐 하나의 MRK 텍스트·MARC 바이너리로 조립된다.

---

## 참고: 이 문서가 다루지 않는 것

- 각 함수의 상세 구현(라인 단위 로직)은 `docs/INTEGRATION_SURVEY.md`의 "핵심 함수
  시그니처" 절과 코드 파일 자체를 직접 열어 확인할 것.
- 4개 원본 폴더를 합친 설계 원칙(왜 이 구조를 택했는지)은 `docs/INTEGRATION_PRINCIPLES.md`
  를 인용할 것 — 이 문서는 "어디를 보면 되는지"만 안내한다.
