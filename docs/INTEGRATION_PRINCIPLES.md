# 통합 원칙 (산출물 2)

041/245/653/260+300 4개 폴더를 하나의 시스템으로 합칠 때 지키는 원칙. 각 원칙은
"규칙 → 근거(어느 폴더의 어떤 불일치 때문인지)" 순서로 정리했다. `docs/INTEGRATION_SURVEY.md`의
조사 결과에 기반한다.

| # | 원칙 | 근거 |
|---|---|---|
| P1 | **알라딘 클라이언트는 `api/aladin_client.py` 하나로 통합하고, `OptResult`는 4개 폴더가 필요로 하던 옵션의 합집합(`OPT_RESULT_FULL`)으로 고정 호출한다.** | 260+300은 `subInfo`/`authors`를 요청하지 않아 041의 번역서 판별이 저하되고, 245는 `fulldescription`/`Toc`가 없고, 653은 `seriesInfo` 등이 없다. 041의 `get_kormarc_tags(item, detail)`이 요구하는 `subInfo.authors[].authorTypeDesc` 등은 245가 요청하는 옵션과 겹치므로, 하나로 합쳐 호출하면 041/245/653 모두가 같은 item 하나로 동작할 수 있다. |
| P2 | **OpenAI 호출 스타일(chat.completions vs responses)은 강제로 통일하지 않는다.** 클라이언트 "생성"만 `api/openai_client.py`로 공통화한다. | 041은 chat.completions 전용, 245는 responses/chat.completions 혼용, 653은 responses+instructions 전용, 260+300은 chat.completions+JSON 강제 전용. 강제로 하나로 바꾸면 653의 instructions 기반 프롬프트나 260+300의 JSON 강제 응답 로직을 재작성해야 해 회귀 위험이 크다. |
| P3 | **OpenAI 클라이언트는 041 방식(함수 인자로 주입)을 표준으로 채택한다.** | 041의 `LangFieldBuilder(openai_client=..., dbg_fn=..., dbg_err_fn=...)`는 이미 프레임워크 독립적으로 설계돼 테스트·목킹이 쉽다. 245(환경변수 직접 읽기)·653(매 호출 `get_settings()`)·260+300(함수 내부에서 직접 생성)은 모두 테스트 시 monkeypatch가 필요해 결합도가 높다. |
| P4 | **설정은 653의 `pydantic-settings` 패턴(`Settings(BaseSettings)` + `.env` + `lru_cache get_settings()`)으로 통일한다.** | 041은 설정 개념 자체가 없고, 245는 `os.environ.get(key, 하드코딩기본값)` 산발적 사용(보안 문제의 원인), 260+300은 `.streamlit/secrets.toml`을 tomllib로 직접 읽는 Streamlit 종속적 방식. pydantic-settings는 타입 검증·기본값·`.env` 지원을 모두 갖추고 653에서 이미 실전 검증됨. |
| P5 | **환경변수 키 이름은 `ALADIN_TTB_KEY` 계열로 통일한다.** 245의 `ALADIN_API_KEY`는 폐기한다. | 260+300·653은 이미 `ALADIN_TTB_KEY`를 쓰는데 245만 `ALADIN_API_KEY`라는 다른 이름을 쓰고, 그 기본값에 실제 키가 하드코딩되어 있었다(보안 문제). 이름부터 통일해야 245를 이식할 때 하드코딩을 함께 제거할 수 있다. |
| P6 | **에러 처리는 260+300의 `(결과, error_msg)` 튜플 반환 패턴을 표준으로 삼는다. 예외를 상위로 던지지 않는다.** | 245는 `raise ValueError`/`requests.RequestException`을 그대로 전파, 653은 `HTTPException` 직접 발생. 041의 `get_kormarc_tags()`는 예외를 잡아 `"📕 예외 발생: …"`이라는 에러 메시지를 **성공 값 자리에 섞어 반환**하는 안티패턴이라 통합 시 반드시 `(tag, error)` 튜플로 고쳐야 한다. |
| P7 | **디버그 로깅은 `core/debug_log.py` 하나를 모든 필드 모듈이 공유하고, 메시지 앞에 `[041]`/`[260]` 같은 필드 프리픽스를 직접 붙인다.** | 260+300은 이미 `_dbg()`/`_dbg_err()` 전역 누적 → `meta["debug_lines"]` 노출 패턴을 갖추고 있고, 041의 `dbg_fn`/`dbg_err_fn` 주입 인자와 시그니처 궁합이 좋다(041의 `dbg_fn` 자리에 `dbg`를 그대로 넘기면 됨). 653은 표준 `logging`만 사용해 사서용 "판단 근거 추적성"이 없으므로 이식 시 보강 대상이다. |
| P8 | **네이밍·타입힌트 스타일은 260+300의 `from __future__ import annotations` + PEP604(`str \| None`) + snake_case + `_` 프라이빗 접두를 프로젝트 전역 표준으로 삼는다.** | 4개 폴더 모두 대체로 이 스타일에 가깝지만, 041만 `Optional[str]`(구식 typing 스타일)을 혼용한다 — 이식 시 `Optional[X]` → `X \| None`으로 일괄 치환한다. |
| P9 | **각 필드 모듈은 "행 자체 완결(row-complete)" 원칙을 따른다**: `core/fields/marc_XXX.py`는 자기 필드 생성에만 책임지고, `(tag_str, pymarc.Field\|None, meta_dict)` 형태로만 반환한다. 다른 필드 모듈이나 app.py의 오케스트레이터를 import하지 않는다. | 이미 260+300의 `build_260_field`/`build_300_field`가 이 형태이고, 041의 `get_kormarc_tags`도 비슷한 반환 형태라 통일 비용이 낮다. 예외: 245는 245/246/500/700/710/900이 `authors`/`orig_title`을 강하게 공유하므로, 표제 계열(`marc_245.py`)과 책임표시 계열(`marc_500_700_710.py`) 2개 파일로 묶는 것만 허용한다. |
| P10 | **레거시 잔재(zip 해제 흔적, 가상환경, 캐시, flatten 이전 흔적 등)는 신규 저장소로 옮기지 않는다.** 삭제 시에는 반드시 원문을 기록으로 남긴다. | `245/__MACOSX`, `245/245/.DS_Store`(zip 해제 잔재), `260+300/.venv`(가상환경, 절대 복사 금지), `260+300/backend_fastapi/`(flatten 이전 흔적) 등. 2026-07-08 정리 작업에서 260+300의 죽은 함수 3개를 삭제하며 `unnecessary/정리_기록_2026-07-08.md`에 원문을 보존한 것이 이 원칙의 실례다. |
| P11 | **영속 계층은 `database/`로 일원화하되, 260+300의 `feedback_logger.py` 스키마(`field_tag` 컬럼)를 그대로 재사용한다.** | `field_tag`가 이미 문자열이라 `"300"`, `"041"`, `"653"` 등 어떤 태그든 스키마 변경 없이 저장 가능하다. `653/sheets_service.py`(골든데이터)와 260+300의 `load_publisher_db`(출판사 DB)는 같은 Google Sheets 인증 정보를 쓰므로 인증 초기화 코드를 공유해야 한다. |

## 알라딘/OpenAI 이외의 부수 이슈 (통합 시 함께 처리)

- **동기/비동기 혼용**: 653은 `async def` + `httpx.AsyncClient` 기반이고 041/245/260+300은
  동기 함수다. 653을 실제 로직으로 이식할 때 `app.py`의 오케스트레이터를 `async def`로
  바꾸고, 나머지 동기 호출부는 `asyncio.to_thread(...)`로 감싸야 한다
  (`core/fields/marc_653.py` 상단 docstring 참고).
- **보안**: 245의 알라딘 키 하드코딩 기본값, `260+300/.streamlit/secrets.toml`에
  남아있던 실제 자격증명 원문은 이 통합 작업과 별개로 사용자가 직접 폐기/재발급해야
  한다(코드 구조 통합으로 해결되는 문제가 아님).
