"""
core/fields/
필드별 MARC 생성 모듈 모음. 담당 필드: 041/546, 245/246/500/700/710/900, 260, 300, 653.

공통 반환 규약 (INTEGRATION_PRINCIPLES.md #9, "행 자체 완결" 원칙):
  각 build_XXX_field() 함수는 (tag_str_or_None, pymarc.Field_or_None, meta_dict) 형태로
  반환하고, 자기 필드 생성에만 책임진다. 다른 필드 모듈이나 app.py의 오케스트레이터를
  import하지 않는다. 예외: marc_245.py/marc_500_700_710.py는 원저자·책임표시 정보를
  강하게 공유하므로 표제 계열/책임표시 계열 2개 파일로만 묶는 것을 허용한다.

디버그 로깅은 core/debug_log.py 하나를 모든 필드 모듈이 공유하며,
호출부에서 메시지 앞에 "[041]", "[260]" 같은 필드 프리픽스를 직접 붙인다.
"""
