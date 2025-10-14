# MinerU 헤더/푸터/페이지번호 처리 분석

## 1. 핵심 발견 사항

### 1.1 요약
MinerU는 **헤더, 푸터, 페이지번호를 `discarded_blocks`로 분류**하여 **최종 Markdown 출력에서 제외**합니다.

**중요**:
- ✅ `discarded_blocks`도 **OCR 처리는 됩니다** (캐릭터 정보 포함)
- ✅ `middle_json`에 **저장됩니다** (`page_info['discarded_blocks']`)
- ❌ **Markdown/content_list 생성 시 무시됩니다**

---

## 2. 백엔드별 처리 방식

### 2.1 VLM 백엔드 (VLM 2.5)

**파일**: `mineru/backend/vlm/vlm_magic_model.py`

#### 지원하는 메타정보 블록 타입 (51-66줄)
```python
if block_type in [
    "text",
    "title",
    "image_caption",
    "image_footnote",
    "table_caption",
    "table_footnote",
    "code_caption",
    "ref_text",
    "phonetic",
    "header",        # ← 헤더
    "footer",        # ← 푸터
    "page_number",   # ← 페이지번호
    "aside_text",    # ← 사이드 텍스트
    "page_footnote", # ← 페이지 각주
    "list"
]:
    span_type = ContentType.TEXT
```

#### discarded_blocks 분류 (204-205줄)
```python
elif block["type"] in [
    BlockType.HEADER,
    BlockType.FOOTER,
    BlockType.PAGE_NUMBER,
    BlockType.ASIDE_TEXT,
    BlockType.PAGE_FOOTNOTE
]:
    self.discarded_blocks.append(block)
```

**결론**: VLM 백엔드는 5가지 메타정보 타입을 명시적으로 `discarded_blocks`로 분류합니다.

---

### 2.2 Pipeline 백엔드

**파일**: `mineru/backend/pipeline/pipeline_magic_model.py`

#### discarded_blocks 분류 (296-298줄)
```python
def get_discarded(self) -> list:
    blocks = self.__get_blocks_by_type(CategoryId.Abandon)
    return blocks
```

**CategoryId.Abandon = 2** (enum_class.py:44)

#### 특징
- Pipeline 백엔드는 `CategoryId.Abandon`만 discarded로 처리
- **헤더/푸터를 명시적으로 감지하는 로직 없음**
- 모델이 `Abandon` 카테고리로 분류한 블록만 제외됨

**결론**: Pipeline 백엔드는 레이아웃 감지 모델의 판단에 의존합니다.

---

## 3. 데이터 흐름 분석

### 3.1 OCR 처리 단계

**파일**: `mineru/backend/pipeline/model_json_to_middle_json.py`

#### 1단계: discarded_blocks 추출 (37줄)
```python
discarded_blocks = magic_model.get_discarded()
```

#### 2단계: span 매핑 (144-148줄)
```python
"""先处理不需要排版的discarded_blocks"""
discarded_block_with_spans, spans = fill_spans_in_blocks(
    all_discarded_blocks, spans, 0.4
)
fix_discarded_blocks = fix_discarded_block(discarded_block_with_spans)
```

**중요**: `fill_spans_in_blocks`는 `discarded_blocks`에도 span(OCR 결과)을 매핑합니다!

#### 3단계: OCR 후처리 (190-228줄)
```python
"""후치ocr 처리"""
need_ocr_list = []
img_crop_list = []
text_block_list = []
for page_info in middle_json["pdf_info"]:
    # preproc_blocks 처리
    for block in page_info['preproc_blocks']:
        ...
    # discarded_blocks도 OCR 처리! (202줄)
    for block in page_info['discarded_blocks']:
        text_block_list.append(block)
```

**결론**: `discarded_blocks`도 완전한 OCR 처리를 거쳐 캐릭터 정보를 포함합니다!

#### 4단계: middle_json 저장 (256-261줄)
```python
def make_page_info_dict(blocks, page_id, page_w, page_h, discarded_blocks):
    return_dict = {
        'preproc_blocks': blocks,
        'page_idx': page_id,
        'page_size': [page_w, page_h],
        'discarded_blocks': discarded_blocks,  # ← 여기 저장됨!
    }
    return return_dict
```

---

### 3.2 Markdown 생성 단계

**파일**: `mineru/backend/pipeline/pipeline_middle_json_mkcontent.py`

#### union_make 함수 (264-290줄)
```python
def union_make(pdf_info_dict: list,
               make_mode: str,
               img_buket_path: str = '',
               ):
    output_content = []
    for page_info in pdf_info_dict:
        paras_of_layout = page_info.get('para_blocks')  # ← para_blocks만 사용!
        page_idx = page_info.get('page_idx')
        page_size = page_info.get('page_size')
        if not paras_of_layout:
            continue
        if make_mode in [MakeMode.MM_MD, MakeMode.NLP_MD]:
            page_markdown = make_blocks_to_markdown(paras_of_layout, make_mode, img_buket_path)
            output_content.extend(page_markdown)
        elif make_mode == MakeMode.CONTENT_LIST:
            for para_block in paras_of_layout:
                para_content = make_blocks_to_content_list(para_block, img_buket_path, page_idx, page_size)
                if para_content:
                    output_content.append(para_content)

    # ... 생략
```

**핵심**:
- `para_blocks`만 처리
- **`discarded_blocks`는 완전히 무시됨**
- Markdown, content_list 어느 모드에서도 포함되지 않음

---

## 4. middle_json 구조

### 4.1 페이지 정보 구조
```json
{
  "pdf_info": [
    {
      "page_idx": 0,
      "page_size": [1078, 1445],
      "preproc_blocks": [
        {
          "type": "text",
          "bbox": [166, 428, 905, 884],
          "lines": [
            {
              "bbox": [169, 429, 894, 466],
              "spans": [
                {
                  "type": "text",
                  "bbox": [169, 429, 894, 466],
                  "content": "본문 내용...",
                  "score": 0.901,
                  "chars": [
                    {"char": "본", "bbox": [169, 429, 185, 466], "char_idx": 0}
                  ]
                }
              ]
            }
          ]
        }
      ],
      "para_blocks": [...],
      "discarded_blocks": [
        {
          "type": "discarded",
          "bbox": [100, 50, 900, 80],
          "lines": [
            {
              "bbox": [100, 50, 900, 80],
              "spans": [
                {
                  "type": "text",
                  "bbox": [100, 50, 900, 80],
                  "content": "Chapter 1 - Page 1",
                  "score": 0.85,
                  "chars": [
                    {"char": "C", "bbox": [100, 50, 115, 80], "char_idx": 0},
                    {"char": "h", "bbox": [116, 50, 131, 80], "char_idx": 1}
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

---

## 5. 사용자 요구사항 구현 방안

### 5.1 문제점
- 헤더/푸터/페이지번호가 `discarded_blocks`에 있음
- `discarded_blocks`는 Markdown 생성 시 무시됨
- 사용자가 원할 때는 이 정보를 포함하고 싶음

### 5.2 해결 방안

#### 방안 A: API 파라미터 추가 (추천)
새 `/layout_ocr` 엔드포인트에 `include_discarded` 파라미터 추가:

```python
@app.post(path="/layout_ocr")
async def layout_ocr(
    files: List[UploadFile] = File(...),
    lang_list: List[str] = Form(["ch"]),
    parse_method: str = Form("auto"),
    include_discarded: bool = Form(False),  # ← 새 파라미터
    start_page_id: int = Form(0),
    end_page_id: int = Form(99999),
):
    # ... 파싱 로직 ...

    # 결과 포맷팅 시 include_discarded에 따라 처리
    result = format_layout_ocr_result(
        middle_json_list,
        pdf_file_names,
        include_discarded=include_discarded
    )
```

**format_layout_ocr_result 수정**:
```python
def format_layout_ocr_result(middle_json_list, pdf_file_names, include_discarded=False):
    result = {
        "status": "success",
        "backend": "pipeline",
        "version": __version__,
        "files": []
    }

    for pdf_idx, middle_json in enumerate(middle_json_list):
        file_result = {
            "filename": pdf_file_names[pdf_idx],
            "pages": []
        }

        for page_info in middle_json["pdf_info"]:
            page_data = {
                "page_index": page_info["page_idx"],
                "page_size": {
                    "width": page_info["page_size"][0],
                    "height": page_info["page_size"][1]
                },
                "layout_boxes": []
            }

            box_id = 0

            # 1. para_blocks 또는 preproc_blocks 처리 (기본)
            blocks = page_info.get("para_blocks") or page_info.get("preproc_blocks", [])
            for block in blocks:
                layout_box = format_block_to_layout_box(block, box_id)
                if layout_box:
                    page_data["layout_boxes"].append(layout_box)
                    box_id += 1

            # 2. discarded_blocks 처리 (옵션)
            if include_discarded:
                discarded_boxes = []
                for block in page_info.get("discarded_blocks", []):
                    layout_box = format_block_to_layout_box(block, box_id)
                    if layout_box:
                        layout_box["is_discarded"] = True  # ← 플래그 추가
                        discarded_boxes.append(layout_box)
                        box_id += 1

                page_data["discarded_boxes"] = discarded_boxes

            file_result["pages"].append(page_data)

        result["files"].append(file_result)

    return result
```

**출력 예시**:
```json
{
  "status": "success",
  "backend": "pipeline",
  "version": "0.9.0",
  "files": [
    {
      "filename": "test.pdf",
      "pages": [
        {
          "page_index": 0,
          "page_size": {"width": 1078, "height": 1445},
          "layout_boxes": [
            {
              "box_id": 0,
              "box_type": "text",
              "bbox": [166, 428, 905, 884],
              "lines": [...]
            }
          ],
          "discarded_boxes": [
            {
              "box_id": 10,
              "box_type": "discarded",
              "bbox": [100, 50, 900, 80],
              "is_discarded": true,
              "lines": [
                {
                  "line_index": 0,
                  "bbox": [100, 50, 900, 80],
                  "text": "Chapter 1 - Page 1",
                  "spans": [
                    {
                      "type": "text",
                      "bbox": [100, 50, 900, 80],
                      "score": 0.85,
                      "content": "Chapter 1 - Page 1",
                      "characters": [
                        {"char": "C", "bbox": [100, 50, 115, 80], "char_index": 0},
                        {"char": "h", "bbox": [116, 50, 131, 80], "char_index": 1}
                      ]
                    }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

#### 방안 B: 별도 필드로 포함 (대안)
`include_discarded=true`일 때 `layout_boxes`에 통합:

```python
# format_layout_ocr_result 수정
if include_discarded:
    for block in page_info.get("discarded_blocks", []):
        layout_box = format_block_to_layout_box(block, box_id)
        if layout_box:
            layout_box["block_category"] = "discarded"  # 카테고리 표시
            page_data["layout_boxes"].append(layout_box)
            box_id += 1
```

**출력 예시**:
```json
{
  "layout_boxes": [
    {
      "box_id": 0,
      "box_type": "text",
      "block_category": "normal",
      "bbox": [166, 428, 905, 884],
      "lines": [...]
    },
    {
      "box_id": 10,
      "box_type": "discarded",
      "block_category": "discarded",
      "bbox": [100, 50, 900, 80],
      "lines": [...]
    }
  ]
}
```

#### 방안 C: VLM 백엔드 사용 (타입별 구분 가능)
VLM 백엔드를 사용하면 HEADER, FOOTER, PAGE_NUMBER를 개별적으로 식별 가능:

```json
{
  "layout_boxes": [
    {
      "box_id": 0,
      "box_type": "header",
      "bbox": [100, 20, 900, 50],
      "lines": [...]
    },
    {
      "box_id": 1,
      "box_type": "footer",
      "bbox": [100, 1400, 900, 1430],
      "lines": [...]
    },
    {
      "box_id": 2,
      "box_type": "page_number",
      "bbox": [500, 1410, 550, 1435],
      "lines": [...]
    }
  ]
}
```

**장점**: 헤더/푸터/페이지번호를 명확히 구분 가능
**단점**: VLM 백엔드 필요 (느림, 더 많은 메모리)

---

## 6. 구현 권장사항

### 6.1 단계별 구현

#### Phase 1: 기본 구현 (1-2시간)
1. ✅ `/layout_ocr` 엔드포인트에 `include_discarded` 파라미터 추가
2. ✅ `format_layout_ocr_result`에서 `discarded_blocks` 처리 로직 추가
3. ✅ 기본 테스트 (헤더/푸터가 있는 PDF)

#### Phase 2: 타입 구분 (선택사항, +1-2시간)
1. ⭕ VLM 백엔드 지원 추가
2. ⭕ `box_type`을 "header", "footer", "page_number"로 구분
3. ⭕ `backend` 파라미터로 선택 가능하게 구현

#### Phase 3: 필터링 옵션 (선택사항, +1시간)
1. ⭕ `include_types` 파라미터 추가: `["header", "footer", "page_number"]`
2. ⭕ 원하는 타입만 선택적으로 포함

```python
@app.post(path="/layout_ocr")
async def layout_ocr(
    files: List[UploadFile] = File(...),
    include_discarded: bool = Form(False),
    include_types: List[str] = Form(None),  # ["header", "footer", "page_number"]
    backend: str = Form("pipeline"),  # "pipeline" 또는 "vlm-*"
):
    # ... 로직 ...
```

---

## 7. 테스트 케이스

### 7.1 테스트 PDF 유형
1. **학술 논문**: 헤더에 저널명, 푸터에 페이지번호
2. **책**: 챕터명 헤더, 페이지번호 푸터
3. **보고서**: 회사명 헤더, 날짜 푸터
4. **잡지**: 복잡한 헤더/푸터 레이아웃

### 7.2 검증 항목
- ✅ `include_discarded=false`: discarded_blocks 미포함 확인
- ✅ `include_discarded=true`: discarded_blocks 포함 확인
- ✅ discarded_blocks의 OCR 정보(chars) 포함 확인
- ✅ bbox 좌표 정확성 검증
- ✅ VLM 백엔드: 타입 구분 정확성 검증

### 7.3 테스트 코드
```python
# tests/test_discarded_blocks.py

def test_layout_ocr_without_discarded():
    """include_discarded=false일 때 discarded_blocks가 포함되지 않는지 테스트"""
    response = requests.post(
        "http://localhost:8000/layout_ocr",
        files={"files": open("test_with_header.pdf", "rb")},
        data={"include_discarded": "false"}
    )
    result = response.json()
    page = result["files"][0]["pages"][0]

    assert "discarded_boxes" not in page
    assert all(box["block_category"] != "discarded" for box in page["layout_boxes"])

def test_layout_ocr_with_discarded():
    """include_discarded=true일 때 discarded_blocks가 포함되는지 테스트"""
    response = requests.post(
        "http://localhost:8000/layout_ocr",
        files={"files": open("test_with_header.pdf", "rb")},
        data={"include_discarded": "true"}
    )
    result = response.json()
    page = result["files"][0]["pages"][0]

    assert "discarded_boxes" in page
    assert len(page["discarded_boxes"]) > 0

    # OCR 정보 확인
    discarded_box = page["discarded_boxes"][0]
    assert "lines" in discarded_box
    assert "characters" in discarded_box["lines"][0]["spans"][0]

def test_vlm_backend_type_detection():
    """VLM 백엔드가 헤더/푸터를 올바르게 식별하는지 테스트"""
    response = requests.post(
        "http://localhost:8000/layout_ocr",
        files={"files": open("test_with_header.pdf", "rb")},
        data={
            "backend": "vlm-huggingface",
            "include_discarded": "true"
        }
    )
    result = response.json()

    discarded_boxes = result["files"][0]["pages"][0]["discarded_boxes"]
    types = [box["box_type"] for box in discarded_boxes]

    assert "header" in types or "footer" in types or "page_number" in types
```

---

## 8. 성능 영향

### 8.1 메모리
- `discarded_blocks`는 이미 `middle_json`에 저장됨
- `include_discarded=true`로 인한 추가 메모리: **거의 없음** (포인터만 복사)

### 8.2 처리 시간
- `discarded_blocks`는 이미 OCR 처리됨
- 포맷팅 시간 증가: **+0.1초 미만** (블록 몇 개 추가)

### 8.3 응답 크기
- discarded_blocks는 보통 페이지당 1-3개
- JSON 크기 증가: **+1-5KB per page**

**결론**: 성능 영향 미미함

---

## 9. 결론

### 9.1 핵심 정리
1. ✅ **데이터는 이미 존재함**: `discarded_blocks`에 OCR 정보 포함
2. ✅ **구현 간단함**: 포맷팅 함수만 수정
3. ✅ **성능 영향 없음**: 추가 처리 불필요
4. ✅ **호환성 유지**: 기본값 `include_discarded=false`로 기존 동작 유지

### 9.2 권장 구현
- **단기**: 방안 A (별도 필드 `discarded_boxes`) + Pipeline 백엔드
- **중기**: VLM 백엔드 지원 추가 (타입 구분)
- **장기**: 필터링 옵션 (`include_types`)

### 9.3 사용 예시
```python
# 헤더/푸터 무시 (기본)
response = requests.post(
    "http://localhost:8000/layout_ocr",
    files={"files": open("paper.pdf", "rb")},
    data={"include_discarded": "false"}
)

# 헤더/푸터 포함
response = requests.post(
    "http://localhost:8000/layout_ocr",
    files={"files": open("paper.pdf", "rb")},
    data={"include_discarded": "true"}
)

# VLM 백엔드로 타입 구분
response = requests.post(
    "http://localhost:8000/layout_ocr",
    files={"files": open("paper.pdf", "rb")},
    data={
        "backend": "vlm-huggingface",
        "include_discarded": "true"
    }
)
```

### 9.4 다음 단계
1. `new_api_dev.md`에 `include_discarded` 파라미터 추가
2. `format_layout_ocr_result` 함수에 discarded_blocks 처리 로직 추가
3. 테스트 케이스 작성
4. API 문서 업데이트
