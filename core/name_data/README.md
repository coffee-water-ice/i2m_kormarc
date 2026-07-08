# core/name_data/ — STUB

245 폴더의 이름판별 데이터 자산이 이식될 자리. 700/710 필드(개인명 부출/기관명 부출)의
지시기호(성 유무, 개인명 vs 단체명) 판별에 쓰인다.

## 이식 대상 (원본: `245/245/`)

| 원본 파일 | 역할 | 옮길 위치 |
|---|---|---|
| `korean_surnames.py` | 한국 성씨 사전(frozenset, 길이별 인덱스) — 700 두 번째 지시기호 판별 | `core/name_data/korean_surnames.py` |
| `korean_given_names.py` | 출생신고 통계 기반 이름 음절 판별 — 필명/실명 구분 | `core/name_data/korean_given_names.py` |
| `korean_real_name_allowlist.py` | 2글자 필명 중 실명 취급할 예외 목록(한강/백석/이상 등) | `core/name_data/korean_real_name_allowlist.py` |
| `japanese_surnames.py` | 일본 성씨 한글 표기 사전 — 국적 판별 보조 신호 | `core/name_data/japanese_surnames.py` |
| `data/korean_given_name_weights.tsv` | 이름 음절 빈도 원본 데이터(대법원 전자가족관계등록 기반, 2008~2019) | `core/name_data/data/korean_given_name_weights.tsv` |

`core/fields/marc_500_700_710.py`를 실제 로직으로 이식할 때 위 5개 파일을 그대로
복사해 오면 된다(245 원본이 이미 로직과 데이터를 분리해 둔 상태라 별도 리팩터링 불필요).
