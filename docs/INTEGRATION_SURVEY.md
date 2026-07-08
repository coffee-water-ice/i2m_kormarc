# 설명서 — 4개 폴더 구조/내용 조사 (산출물 1)

4개 폴더 모두 **KORMARC(한국문헌자동화목록법) 서지레코드 자동 생성기**의 구성요소다.
사서가 ISBN을 입력하면 알라딘 Open API 등에서 도서 메타데이터를 가져와 GPT(OpenAI)의
도움을 받아 KORMARC 각 필드를 자동으로 채워주는 도구이며, 폴더마다 담당하는 MARC
필드가 다르다.

## 필드 담당 매트릭스

| MARC 필드 | 의미 | 담당 폴더 |
|---|---|---|
| 041 | 언어코드 | `041` |
| 546 | 언어주기 | `041` |
| 245 | 표제/책임표시 | `245` |
| 246 | 원서명 | `245` |
| 500 | 원저자명 주기 | `245` |
| 700 | 개인명 부출 | `245` |
| 710 | 기관명 부출 | `245` |
| 900 | 원저자 한글명 | `245` |
| 260 | 발행사항 | `260+300` |
| 300 | 형태사항 | `260+300` |
| 653 | 자유주제어 | `653` |

---

## 041 폴더

### 1. 역할
단일 파일 `041.py`(1976줄). `LangFieldBuilder` 클래스가 041(언어코드)/546(언어주기)
필드를 생성한다. 본문 언어($a)와 원서 언어($h)를 판별해, 예를 들어 번역서면
`041 $akor $heng` + `546 텍스트`를 만든다.

### 2. 진입점
없음 — 실행 스크립트가 아니라 **라이브러리 모듈**. 어떤 호스트 앱에서도 아직
import되고 있지 않다(245/app.py 포함 grep 결과 0건 — 미통합 상태).

```python
from lang_field import LangFieldBuilder
builder = LangFieldBuilder(openai_client=client, dbg_fn=dbg, dbg_err_fn=dbg_err)
tag_041, tag_546, orig_title = builder.get_kormarc_tags(item, detail)
```

### 3. 파일 트리
```
041/
└── 041.py   (1976줄, 단일 파일)
```
파일 내부 docstring에 원래 모듈명이 `lang_field.py`였다고 적혀 있다(폴더명 규칙에
맞춰 리네임된 것으로 추정).

### 4. 핵심 함수 시그니처
| 구성요소 | 위치 | 역할 |
|---|---|---|
| `ISDS_LANGUAGE_CODES`, `ALLOWED_CODES` | 63~77행 | ISO 639-2 유사 언어코드 상수 |
| `AladinAuthorScraper` 클래스 | 330~586행 | 알라딘 저자 프로필 페이지에서 bio 텍스트 크롤링 |
| `LangFieldBuilder` 클래스 | 587~1944행 | 메인 엔진 — 키워드 사전, GPT 호출, 규칙기반 탐지 |
| `LangFieldBuilder.determine_h_language()` | 1419행 | 원서 언어 결정 핵심 로직 |
| `LangFieldBuilder.get_kormarc_tags(item, detail)` | 1749행 | 최종 API — `(tag_041, tag_546, orig_title)` 반환 |
| `generate_546_from_041()` | — | 546 텍스트 생성 |

### 5. 알라딘 API 사용 방식
자체 API 호출 없음(item을 인자로 받음). 단, `AladinAuthorScraper`가 저자 페이지를
HTML 크롤링(API 키 불필요)해서 bio 텍스트를 보조 신호로 사용한다.
`get_kormarc_tags(item, detail)`가 기대하는 item 키: `title`, `publisher`, `author`,
`categoryName`(또는 버그로 `categoryText`), `subInfo.originalTitle`,
`subInfo.authors[].{authorName, authorTypeDesc, authorId, ...}`,
`fulldescription`/`Toc`(보조).

### 6. OpenAI 사용 방식
`openai_client`를 생성자에서 **주입**받는다(직접 import 안 함) — 245/653/260+300과
달리 이미 프레임워크 독립적으로 설계됨. `dbg_fn`/`dbg_err_fn` 로거도 호출부 주입 방식.

### 7. 설정 관리 방식
없음(주입식이라 환경변수 자체가 불필요).

### 8. 의존 라이브러리
`requirements.txt` 없음. `requests`, `bs4.BeautifulSoup`을 선택적 import(try/except로
없어도 모듈 자체는 로드되게 설계).

### 9. 고유 자산
`AladinAuthorScraper` — 다른 폴더에 없는, 알라딘 저자 프로필 페이지 bio 크롤러.

### 10. 알려진 이슈
- `get_kormarc_tags()` 1780행 부근에 `item.get("categoryText", "")` 단독 호출 버그.
  실제 알라딘 API 필드명은 `categoryName`이며(914행에서는 이미
  `item.get("categoryName") or item.get("categoryText")`로 올바르게 처리), 1780행만
  단독으로 남아 있어 사실상 항상 빈 문자열이 된다.
- `get_kormarc_tags()` 전체가 try/except로 감싸져 있고, 실패 시 문자열
  `"📕 예외 발생: …"`을 성공 값 자리에 섞어 반환하는 안티패턴(1852~1854행).

---

## 245 폴더

### 1. 역할
표제(245/246/900)와 책임표시·원저자(500/700/710) 필드를 생성하는 완결된 배포형
웹 서비스.

### 2. 진입점
- 백엔드: `cd backend && python app.py` (로컬, `localhost:5000`) 또는 배포 시
  `gunicorn app:app`.
- 프론트엔드: `streamlit run streamlit_app.py` (로컬 `localhost:8501`).
- `wsgi.py`가 `app.py`를 동적 import로 로드해 gunicorn에 노출.

### 3. 파일 트리
```
245/
├── 245/                              ← 실질 콘텐츠 (한 단계 더 들어간 구조)
│   ├── app.py                        # Flask 백엔드 (3404줄) — 실제 KORMARC 생성 엔진
│   ├── streamlit_app.py              # Streamlit 프론트엔드
│   ├── wsgi.py                       # gunicorn 진입점
│   ├── nlk_opac.py                   # 국립중앙도서관(NLK) OPAC 스크레이핑
│   ├── korean_surnames.py            # 한국 성씨 사전
│   ├── korean_given_names.py         # 이름 음절 판별(필명/실명 구분)
│   ├── korean_real_name_allowlist.py # 2글자 필명 예외 허용목록
│   ├── japanese_surnames.py          # 일본 성씨 사전(한글 표기)
│   ├── data/korean_given_name_weights.tsv
│   ├── README_v2.md, requirements.txt, requirements_streamlit.txt, runtime.txt, render.yaml
└── __MACOSX/                         # zip 압축 해제 잔재 (실제 코드 아님)
```
`245` 폴더 자체가 zip 압축 해제 흔적(`__MACOSX`, `.DS_Store`)을 포함하고, 실제 코드는
`245\245\` 하위에 이중 중첩되어 있다.

### 4. 핵심 함수 시그니처
`fetch_aladin(isbn)`, `scrape_aladin_product(item_id)`(1406행), `korean_name_reverse()`,
`english_name_reverse()`, `build_245()`~`build_900()`, `_gpt_orig_info_lookup()`,
라우트 `/api/isbn`(2822행).

### 5. 알라딘 API 사용 방식
`OptResult=authors,subInfo,seriesInfo`로 호출. `subInfo.originalTitle`,
`subInfo.authors[].{authorName, authorTypeDesc, authorId}`가 채워짐(041이 기대하는
구조와 호환). 단 `fulldescription`/`Toc`는 요청하지 않음.
`ALADIN_API_KEY = os.environ.get("ALADIN_API_KEY", "ttbboyeong09010919001")` —
**기본값에 실제 키가 하드코딩**되어 있다(보안 문제).

### 6. OpenAI 사용 방식
`OPENAI_API_KEY` 환경변수로 직접 `openai` 모듈 사용. 한 파일 안에서
`responses.create`(1769행)와 `chat.completions.create`(2422행)를 **혼용**.

### 7. 설정 관리 방식
`os.environ.get(key, 하드코딩기본값)` 산발적 사용.

### 8. 의존 라이브러리
`requirements.txt`(flask, flask-cors, requests, gunicorn, beautifulsoup4, hanja,
pykakasi, jaconv, streamlit, openai), `requirements_streamlit.txt`(streamlit, requests).
`runtime.txt` → `python-3.11.9`.

### 9. 고유 자산
한국어/일본어 이름판별 데이터 4종 + TSV(다른 폴더에 전혀 없음, 700/710 지시기호
판별에 필수) — `core/name_data/README.md` 참고. `nlk_opac.py`(NLK OPAC MARC 조회).

### 10. 알려진 이슈
- 알라딘 API 키 하드코딩 노출(`app.py:106`).
- OpenAI 호출 방식 혼용(responses/chat.completions).
- zip 해제 잔재(`__MACOSX`, 이중 중첩 폴더) 정리 필요.

---

## 653 폴더

### 1. 역할
FastAPI 백엔드(`backend/app/`) + Streamlit 프론트. 653(자유주제어) 필드를 생성.
ISBN → 메타데이터 수집(알라딘 필수 + KPIPA/Seoji 선택) → 병합·전처리 → 18개 분야 중
하나로 라우팅 → 분야별 프롬프트로 OpenAI 호출 → 금지어·저효용어 필터링 → 3단 폴백 →
`=653 $a키워드1$a키워드2…` 반환.

### 2. 진입점
```bash
cd backend && uvicorn app.main:app --reload   # http://127.0.0.1:8000/health
streamlit run streamlit_app/app.py            # 루트에서, 백엔드가 먼저 떠 있어야 함
```

### 3. 파일 트리
```
653/
├── backend/app/
│   ├── main.py            # FastAPI 엔트리 — 라우트·TTL 캐시·lifespan
│   ├── config.py          # pydantic-settings 환경설정
│   ├── models.py          # 요청/응답 Pydantic 스키마
│   ├── ai_service.py      # 1239줄 — 분야별 프롬프트·필터링·OpenAI 호출 (핵심 로직)
│   ├── fetcher.py         # 하위호환 재-export
│   ├── fetcher_http.py    # 공용 HTTP 재시도·SSL 폴백
│   ├── aladin_client.py   # 알라딘 ItemLookUp + 상세페이지 크롤링
│   ├── kpipa_client.py    # KPIPA getBookDetail(ONIX 목차) 클라이언트
│   ├── nlk_client.py, nlk_metadata.py  # NLK/Seoji 클라이언트(보조/제한적 사용)
│   ├── metadata_merge.py  # 알라딘+KPIPA 메타 병합
│   ├── preprocess.py      # 텍스트 정제·금지어 필터
│   ├── sheets_service.py  # Google Sheets 골든데이터 저장
│   └── few_shots.json     # 분야별 few-shot 예시 DB
└── streamlit_app/
    ├── app.py              # 단건조회/배치처리/품질평가 3탭 UI
    └── quality_rubric.py   # 사서 라벨링용 평가 컬럼/기준
```

### 4. 핵심 함수 시그니처
`main.py`: `POST /api/field653`(TTL 캐시 내장 `_TtlCache`), `POST /api/field653/preview`,
`GET /api/sheets-check`, `POST /api/save-golden`.
`ai_service.py`: `CATEGORY_PROMPTS`(18개 분야), `get_category_group()`,
`kdc_content_code_to_group()`, `_call_learned_agent_api()`, `finalize_653()`
(①AI 원출력 필터링 → ②텍스트 토크나이즈 백업 → ③카테고리 기반 대체어 3단 폴백).

### 5. 알라딘 API 사용 방식
`OptResult=Toc,authors,fulldescription`. `fulldescription`은 041이 기대하는 보조
텍스트 소스와 호환되지만, `authors`를 041이 기대하는 구조화된 딕셔너리로 활용하지
않고 단순 문자열(`clean_author_str`)로만 처리.

### 6. OpenAI 사용 방식
**Responses API**(`client.responses.create`, `instructions` 파라미터 방식). 과거
Conversation ID 방식에서 "턴 누적 문제"로 전환됨(`config.py` 주석).

### 7. 설정 관리 방식
`pydantic_settings.BaseSettings` + `.env`(`backend/app/../../.env` 로드) +
`lru_cache get_settings()`.

### 8. 의존 라이브러리
`fastapi`, `uvicorn`, `pydantic`+`pydantic-settings`, `httpx`(비동기), `openai>=2.0`,
`tenacity`(재시도), `beautifulsoup4`, `gspread`+`google-auth`, `playwright`(선택,
실제로는 `getContents.aspx` 직접 크롤링으로 대체된 상태), `streamlit`, `pandas`,
`python-dotenv`, `openpyxl`.

### 9. 고유 자산
18개 분야별 프롬프트 체계(`CATEGORY_PROMPTS`), `few_shots.json`, Google Sheets
골든데이터 저장(`sheets_service.py`), TTL 캐시(`_TtlCache`).

### 10. 알려진 이슈
`GOOGLE_SERVICE_ACCOUNT`/`GOOGLE_SHEETS_ID`가 `.env.example`에 없어 배포 환경에만
설정되어 있을 가능성 — 통합 시 출처 확인 필요. 표준 `logging`만 사용해 260+300 같은
"사서용 판단 근거 추적성"(`debug_lines`)이 없음.

---

## 260+300 폴더 (통합 프레임워크의 기준)

### 1. 역할
ISBN → MARC 변환 서비스. 알라딘 조회 → 발행지 다중 소스 판정 → 260(발행사항)/300
(형태사항) 생성 → MRK 텍스트 + MARC 바이너리(base64) + 메타데이터 JSON 반환 →
사서 수정 이력을 SQLite에 피드백으로 저장.

### 2. 진입점
```bash
uvicorn app:app --reload        # http://127.0.0.1:8000, Swagger /docs
streamlit run streamlit_app.py  # http://localhost:8501
```
엔드포인트: `GET /health`, `POST /api/convert`, `POST /api/convert/batch`,
`GET /api/kpipa/{isbn}`, `POST /api/feedback`.

### 3. 파일 트리 (2026-07-08 정리 후 기준)
```
260+300/
├── app.py, streamlit_app.py, api_client.py
├── core/
│   ├── marc_builder.py   # pymarc.Record ↔ MRK 변환
│   └── field_rules.py    # 260/300 생성 규칙
├── api/
│   └── external_apis.py  # 알라딘/KPIPA/행안부/Google Sheets 연동, build_pub_location_bundle
├── database/
│   └── feedback_logger.py  # SQLite 피드백 CRUD
├── kpipa_steps/           # KPIPA 출판사 DB 주간 자동 갱신 (GitHub Actions가 kpipa_step3.py만 호출)
├── .github/workflows/kpipa_weekly.yml
├── README.md / CLAUDE.md / PROJECT_CODE_GUIDE.md
└── unnecessary/           # 정리된 레거시 파일 아카이브 (정리_기록_2026-07-08.md 참고)
```

### 4. 핵심 함수 시그니처
`build_260_field(place_display, publisher_name, pubyear, publisher_name2) -> (str, Field|None)`,
`build_300_field(item, isbn, secrets) -> (str, Field, dict)`,
`build_pub_location_bundle(isbn, publisher_name_raw, secrets) -> dict`
(5단계 체인, `source` 필드로 판정 경로 태깅),
`get_aladin_item_by_isbn(isbn, secrets) -> (dict, str|None)`.

### 5. 알라딘 API 사용 방식
원래 `OptResult=ebookList,usedList,reviewList,fileFormatList,packing,subbarcode`만
요청 — `subInfo`/`authors`/`Toc`/`fulldescription` 없음. i2m_kormarc 골격에서는
041/245/653이 필요로 하는 옵션까지 합쳐 `OPT_RESULT_FULL`로 확장했다
(`api/aladin_client.py` 참고).

### 6. OpenAI 사용 방식
`openai.OpenAI(api_key=...).chat.completions.create(response_format={"type":"json_object"})`
— 300 $b(삽화) 판정에 gpt-4o-mini 사용, 함수 내부에서 클라이언트를 직접 생성.

### 7. 설정 관리 방식
`.streamlit/secrets.toml`(로컬) 또는 환경변수(배포) — `_load_runtime_secrets()`가
두 소스를 병합(환경변수 우선). i2m_kormarc 골격에서는 653 패턴(pydantic-settings)으로
통일했다(`core/config.py`).

### 8. 의존 라이브러리
`fastapi`, `uvicorn`, `pydantic`, `requests`, `beautifulsoup4`, `pymarc`, `gspread`,
`oauth2client`, `pandas`, `openpyxl`, `openai`, `python-dotenv`, `google-auth`.

### 9. 고유 자산
`build_pub_location_bundle()`의 5단계 우선순위 체인(Chain of Responsibility),
`kpipa_steps/`의 GitHub Actions 자동화, 3단 문서 체계(README/CLAUDE/PROJECT_CODE_GUIDE).

### 10. 알려진 이슈 (2026-07-08 정리로 해소됨)
과거 문체부(MCST) 크롤링 기반 발행지 조회 함수 3개(`get_mcst_address`,
`get_publisher_name_from_isbn_kpipa`, `find_main_publisher_from_imprints`)가 죽은
코드로 남아있었으나 삭제 완료 — 원문은 `260+300/unnecessary/정리_기록_2026-07-08.md`
참고. `kpipa_steps/`의 1회성 부트스트랩 스크립트(`kpipa_step1.py`, `kpipa_step2.py`)와
구버전 설계 문서(`KPIPA_DB_GUIDE.md`)도 같은 시점에 `unnecessary/`로 이동.

---

## 알라딘 item/detail 필드 호환성 비교 (통합 시 핵심 참고)

| 필드 모듈 | 요청 OptResult | subInfo/authors 확보 | fulldescription/Toc 확보 |
|---|---|---|---|
| 260+300 (원본) | ebookList 등 | ✗ | ✗ |
| 245 | authors,subInfo,seriesInfo | ✓ | ✗ |
| 653 | Toc,authors,fulldescription | 부분(구조화 안 함) | ✓ |
| **i2m_kormarc (통합 후)** | **OPT_RESULT_FULL(합집합)** | **✓** | **✓** |

041의 `get_kormarc_tags(item, detail)`은 `subInfo.authors[].{authorTypeDesc, authorId,
authorBio 등}`을 기대하는데, 260+300 원본 경로로만 item을 얻으면 이 정보가 없어
번역서 판별(`_has_translator_in_item`)이 `item.author` 원문 정규식 fallback만 타게
되어 정확도가 떨어진다. `api/aladin_client.OPT_RESULT_FULL`로 통합 호출하면 해결된다.

`detail` 인자는 041/245/653/260+300 어느 폴더에서도 아직 생성되지 않는 "가상의"
파라미터다 — 041의 041/546 로직 자체는 `subject_lang or ""`로 안전하게 처리하므로
`detail={}`로 호출해도 최소 동작은 하지만, `AladinAuthorScraper`의 bio 텍스트를
`detail`에 채워 넣는 것은 041을 실제 로직으로 이식할 때의 개선 과제로 남는다.
