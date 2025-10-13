```
mineru cli 메인 (mineru.cli.client.main())
├── 실행옵션 주입 (kwargs.update, os.environ 업데이트)
│   ├── 추가 CLI 인수 파싱 (arg_parse())
│   ├── 조건문: backend가 '-client'로 끝나지 않으면 (원격이 아닌 로컬에서 파싱이 일어난다면)
│   │   ├── 디바이스 모드 설정 (get_device_mode())
│   │   ├── 가상 VRAM 크기 설정 (get_virtual_vram_size())
│   │   └── 모델 소스 설정
│   └── 출력 디렉토리 생성
└── 문서파싱 실행 (parse_doc())
    ├── 조건문: 입력이 디렉토리인지 파일인지 판단
    ├── 파일 목록 구성 (디렉토리면 glob으로 PDF/이미지 파일 수집)
    └── 실제 파싱 로직 (parse_doc 내부함수)
        ├── 루프: 파일 목록을 순회하며
        │   ├── 파일명 추출 (stem만)
        │   ├── 파일을 바이트로 읽기 (read_fn())
        │   └── 언어 정보 추가 (CLI로 받은 lang 파라미터)
        └── 통합 파싱 실행 (do_parse())
            ├── PDF 전처리 (prepare 단계)
            │   ├── 조건문: 페이지 범위가 전체가 아니면
            │   ├── 루프: PDF 목록을 순회하며
            │   └── 페이지 범위 추출 (convert_pdf_bytes_to_bytes_by_pypdfium2())->처리할 페이지 잘라내기
            └── 백엔드별 처리 (process 단계)
                ├── 조건문: backend가 "pipeline"이면
                │   └── Pipeline 처리 (_process_pipeline())
                │       ├── 루프: PDF 목록을 순회하며
                │       ├── 환경 준비 (prepare_env())
                │       ├── 단계별 ML 파이프라인 실행 (doc_analyze())
                │       │   ├── PDF 타입 판정 및 OCR 모드 결정 (classify())
                │       │   ├── PDF 페이지 → 이미지 변환 (load_images_from_pdf())
                │       │   ├── 배치 구성 및 실행 준비 (MINERU_MIN_BATCH_INFERENCE_SIZE 기반 분할)
                │       │   └── 배치 이미지 분석 (batch_image_analyze())
                │       │       ├── 레이아웃 감지 (DocLayoutYOLO)
                │       │       ├── 수식 검출(MFD) 및 인식(MFR→LaTeX)
                │       │       ├── OCR 텍스트 검출 (언어/해상도별 배치, 수식영역 보정)
                │       │       ├── 표 인식 (RapidTableModel→HTML)
                │       │       └── OCR 텍스트 인식 (언어별 그룹화 후 recognition)
                │       └── 결과 출력 처리 (_process_output())
                │           ├── 조건문: f_draw_layout_bbox가 True이면
                │           │   └── 레이아웃 바운딩박스 시각화 (draw_layout_bbox())
                │           ├── 조건문: f_draw_span_bbox가 True이면  
                │           │   └── 스팬 바운딩박스 시각화 (draw_span_bbox())
                │           ├── 조건문: f_dump_orig_pdf가 True이면
                │           │   └── 원본 PDF 저장
                │           ├── 조건문: f_dump_md가 True이면
                │           │   └── 마크다운 파일 생성 및 저장 (union_make())
                │           │       ├── 백엔드별 union_make 함수 선택 (pipeline_union_make vs vlm_union_make)
                │           │       ├── 분석결과 → 마크다운 변환 (make_func())
                │           │       │   ├── 루프: 페이지별 처리
                │           │       │   ├── 조건문: make_mode가 MM_MD/NLP_MD이면
                │           │       │   │   └── 블록별 마크다운 변환 (make_blocks_to_markdown())
                │           │       │   │       ├── 루프: para_block을 순회하며
                │           │       │   │       ├── 조건문: 블록 타입별 분기 처리
                │           │       │   │       │   ├── TEXT/LIST/INDEX → 텍스트 병합
                │           │       │   │       │   ├── TITLE → 헤더 레벨 처리 (# 개수)
                │           │       │   │       │   ├── INTERLINE_EQUATION → 수식 처리 (LaTeX/이미지)
                │           │       │   │       │   ├── IMAGE → 이미지 링크/각주 처리
                │           │       │   │       │   └── TABLE → HTML 테이블 처리
                │           │       │   │       └── 페이지 마크다운 텍스트 구성
                │           │       │   └── 조건문: make_mode가 CONTENT_LIST이면
                │           │       │       └── 구조화된 콘텐츠 리스트 생성
                │           │       └── 마크다운 파일 저장 (md_writer.write_string())
                │           ├── 조건문: f_dump_content_list가 True이면
                │           │   └── 콘텐츠 리스트 JSON 파일 생성 및 저장 (union_make())
                │           ├── 조건문: f_dump_middle_json이 True이면
                │           │   └── 중간 결과 JSON 파일 저장
                │           └── 조건문: f_dump_model_output이 True이면
                │               ├── 조건문: is_pipeline이면
                │               │   └── 모델 출력을 JSON으로 저장
                │               └── 조건문: VLM이면
                │                   └── 모델 출력을 텍스트로 저장
                └── 조건문: backend가 "vlm-xxx"이면  
                    └── VLM 처리 (_process_vlm())
                        ├── 백엔드명 전처리 (vlm- 접두사 제거)
                        ├── VLM 옵션 환경변수 설정
                        ├── 루프: PDF 목록을 순회하며
                        ├── 환경 준비 (prepare_env())
                        ├── VLM 모델 실행 (vlm_doc_analyze())
                        └── 결과 출력 처리 (_process_output())
                            ├── 조건문: f_draw_layout_bbox가 True이면
                            │   └── 레이아웃 바운딩박스 시각화 (draw_layout_bbox())
                            ├── 조건문: f_draw_span_bbox가 True이면  
                            │   └── 스팬 바운딩박스 시각화 (draw_span_bbox())
                            ├── 조건문: f_dump_orig_pdf가 True이면
                            │   └── 원본 PDF 저장
                            ├── 조건문: f_dump_md가 True이면
                            │   └── 마크다운 파일 생성 및 저장 (union_make())
                            ├── 조건문: f_dump_content_list가 True이면
                            │   └── 콘텐츠 리스트 JSON 파일 생성 및 저장 (union_make())
                            ├── 조건문: f_dump_middle_json이 True이면
                            │   └── 중간 결과 JSON 파일 저장
                            └── 조건문: f_dump_model_output이 True이면
                                ├── 조건문: is_pipeline이면
                                │   └── 모델 출력을 JSON으로 저장
                                └── 조건문: VLM이면
                                    └── 모델 출력을 텍스트로 저장
```

## MinerU 구성상 특징
-MinerU는 4가지 백엔드를 지원합니다:
  1. pipeline - 전통적 ML 파이프라인 (로컬)
  2. vlm-transformers - HuggingFace transformers (로컬)
  3. vlm-sglang-engine - SgLang 엔진 (로컬)
  4. vlm-sglang-client - SgLang 클라이언트 (원격)

## 백엔드별 처리방식
-Pipeline 백엔드 (_process_pipeline)
  - 전통적 ML 파이프라인: 여러 개의 특화된 모델을 순차적으로 실행
  - 단계별 처리: Layout Detection → OCR → Formula Recognition → Table Recognition
  - 모듈식 구조: 각 단계마다 다른 모델 사용 (YOLO, PaddleOCR, UniMERNet 등)
  - 제어 가능: 수식/표 인식 on/off, 언어별 OCR 모델 선택 등

-VLM 백엔드 (_process_vlm)
  - Vision Language Model: 하나의 거대한 모델이 모든 작업을 한번에 처리
  - 엔드투엔드: PDF 이미지를 보고 바로 텍스트+구조 추출
  - AI 기반: GPT-V, Claude-V 같은 멀티모달 모델의 이해력 활용
  - 단순한 구조: 복잡한 파이프라인 없이 모델 하나로 끝

-핵심 차이점:
  - Pipeline: 정교하고 제어 가능하지만 복잡 (여러 모델 조합)
  - VLM: 간단하고 강력하지만 블랙박스 (하나의 큰 모델)

---

## 실행옵션 주입 (kwargs.update, os.environ 업데이트)
- 추가 CLI 옵션들을 파싱하고 환경변수로 설정하여 시스템 전체에서 사용할 수 있도록 준비

---

## 추가 CLI 인수 파싱 (arg_parse())
- `--option=value` 형태의 추가 인수를 동적으로 파싱하여 kwargs에 병합 (타입 자동 변환: bool, int, float, str)

---

## 디바이스 모드 설정 (get_device_mode())
- CLI의 device_mode 옵션이 있으면 사용, 없으면 get_device()로 자동 감지
- MINERU_DEVICE_MODE 환경변수 설정 (cuda, cpu, npu, mps 중 하나)

---

## 가상 VRAM 크기 설정 (get_virtual_vram_size())
- CLI의 virtual_vram 옵션이 있으면 사용, 없으면 get_vram()으로 실제 VRAM 크기 측정
- GPU/NPU가 아니면 기본값 1GB 설정, MINERU_VIRTUAL_VRAM_SIZE 환경변수 설정

---

## 모델 소스 설정
- CLI의 model_source 옵션값을 MINERU_MODEL_SOURCE 환경변수로 설정 (huggingface, modelscope 등)

---

## 문서파싱 실행 (parse_doc())
- 입력 경로가 단일 파일인지 디렉토리인지 판단하여 적절한 파일 목록을 구성한 후 실제 파싱 로직 실행

**파일을 바이트로 읽기 (read_fn())**
- 이미지 파일(.png, .jpg 등)은 PDF로 변환 후 바이트 반환
- PDF 파일은 직접 바이트로 읽기

**통합 파싱 실행 (do_parse())**
- 모든 파일의 메타데이터(파일명, 바이트, 언어)를 수집하여 common.py의 do_parse()로 실제 파싱 작업 위임

**PDF 전처리 (prepare 단계)**
- 사용자가 지정한 페이지 범위에 따라 PDF 바이트 데이터를 필터링하여 처리 대상 페이지만 추출

**페이지 범위 추출 (convert_pdf_bytes_to_bytes_by_pypdfium2())**
- 맥락: 대용량 PDF에서 특정 페이지 범위만 처리하여 성능 최적화
- 입력: PDF 바이트, 시작페이지ID, 종료페이지ID
- 출력: 필터링된 PDF 바이트 (지정된 페이지만 포함)
- 상세설명: pypdfium2 라이브러리를 사용하여 원본 PDF에서 지정 페이지만 추출해 새 PDF 생성. 페이지 범위 검증(음수/범위초과 보정), 메모리 관리(BytesIO 사용), 리소스 정리(close() 호출) 등 안전한 PDF 조작 구현

**백엔드별 처리 (process 단계)**
- 백엔드 타입에 따라 완전히 다른 문서 분석 방식으로 분기하여 처리

**Pipeline 처리 (_process_pipeline())**
- 여러 특화 모델을 순차 실행하는 전통적 ML 파이프라인 방식으로 문서 분석

**단계별 ML 파이프라인 실행 (doc_analyze())**
 - Pipeline 백엔드 핵심 함수로 PDF를 단계별로 분석하여 구조화된 결과를 생성

**실제 처리 단계 개요**
- 1) OCR 모드 결정 (classify): `parse_method`가 'auto'인 경우 `classify(pdf_bytes)`로 ocr/txt 판정하여 페이지별 OCR 사용 여부 설정
- 2) 페이지 렌더링 (load_images_from_pdf): 각 PDF를 페이지 단위 `PIL.Image` 리스트와 `pdf_doc`으로 변환해 보존
- 3) 배치 분할: `MINERU_MIN_BATCH_INFERENCE_SIZE`(기본 384) 기준으로 페이지들을 배치 리스트로 분할
- 4) 배치 이미지 분석 (batch_image_analyze): 다음 서브단계를 순차 수행
  - 레이아웃 감지: DocLayoutYOLO로 블록/표/수식 후보 감지
  - 수식 처리: YOLOv8 MFD(검출) → MFR(인식, LaTeX) 결과를 레이아웃에 병합(옵션)
  - OCR 텍스트 검출: 언어별·해상도별 그룹 배치, 수식 위치 보정 박스 적용 후 검출 결과를 레이아웃에 반영
  - 표 인식: RapidTableModel로 HTML 구조 추출 후 레이아웃에 반영(옵션)
  - OCR 텍스트 인식: 언어별 그룹으로 recognition 실행, 신뢰도 기준에 따라 카테고리 보정

**모델 초기화 위치(정정)**
- MineruPipelineModel 초기화는 `doc_analyze()`의 독립 단계가 아니라 `batch_image_analyze()` 내부에서 `ModelSingleton().get_model()` → `custom_model_init()` 경로로 지연 로드됨. OCR/표 등 원자 모델은 `AtomModelSingleton`에서 필요 시 획득.

**결과 조립과 반환**
- `images_layout_res`를 페이지 순서로 정렬·매핑해 `infer_results`(문서별 페이지 리스트)를 구성하고, 각 페이지에 `page_info(width,height)`를 포함
- 반환: `(infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list)`

**VLM 처리 (_process_vlm())**  
- 하나의 거대한 Vision Language Model로 문서를 한번에 분석하는 엔드투엔드 방식

**환경 준비 (prepare_env())**
- 각 PDF별로 출력 디렉토리와 이미지 저장 디렉토리 생성

**결과 출력 처리 (_process_output())**
- **맥락**: Pipeline/VLM 분석 완료 후 사용자가 요청한 형태의 출력 파일들을 생성하는 최종 단계  
- **입력**: pdf_info(분석결과), pdf_bytes(원본), 파일명, 출력경로, 출력옵션 플래그들(f_dump_xxx), middle_json, model_output, is_pipeline
- **출력**: 다양한 형태의 결과 파일들 - 마크다운(.md), JSON(.json), PDF(바운딩박스/원본), 텍스트(.txt)
- **상세설명**: 14개의 출력 옵션 플래그에 따라 조건부로 파일 생성. 백엔드별 차이점 처리(pipeline은 JSON 저장, VLM은 텍스트 저장). union_make() 함수로 분석 결과를 사용자 친화적 형태(마크다운/콘텐츠리스트)로 변환. FileBasedDataWriter로 실제 파일 쓰기 수행

