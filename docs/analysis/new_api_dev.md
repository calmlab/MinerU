# MinerU Layout OCR API 개발 계획서

## 1. 요구사항 정의

### 1.1 목표
이미지 PDF 경로를 입력받아 페이지별 레이아웃 박스의 bbox 좌표와 박스 내부 캐릭터의 OCR 판독값 및 bbox 좌표를 JSON 형식으로 반환하는 API 엔드포인트 개발

### 1.2 입력
- PDF 또는 이미지 파일 (업로드)
- 언어 설정 (optional)
- OCR 모드 (auto/ocr/txt)

### 1.3 출력 형식
```json
{
  "status": "success",
  "backend": "pipeline",
  "version": "0.9.0",
  "pages": [
    {
      "page_index": 0,
      "page_size": {"width": 1078, "height": 1445},
      "layout_boxes": [
        {
          "box_id": 0,
          "box_type": "text",
          "bbox": [166, 428, 905, 884],
          "score": 0.95,
          "lines": [
            {
              "line_index": 0,
              "bbox": [169, 429, 894, 466],
              "characters": [
                {
                  "char": "책",
                  "bbox": [169, 429, 185, 466],
                  "char_index": 0
                },
                {
                  "char": "에",
                  "bbox": [186, 429, 202, 466],
                  "char_index": 1
                }
              ],
              "text": "책에 바침이란..."
            }
          ]
        },
        {
          "box_id": 1,
          "box_type": "table",
          "bbox": [100, 500, 900, 800],
          "score": 0.92,
          "table_data": {
            "html": "<table>...</table>",
            "latex": "\\begin{table}..."
          },
          "lines": [
            {
              "line_index": 0,
              "bbox": [105, 505, 895, 540],
              "spans": [
                {
                  "type": "text",
                  "bbox": [105, 505, 300, 540],
                  "content": "Header 1",
                  "characters": [...]
                }
              ]
            }
          ]
        },
        {
          "box_id": 2,
          "box_type": "image",
          "bbox": [100, 900, 500, 1200],
          "score": 0.88,
          "image_path": "image/abc123_2.jpg",
          "caption": {
            "bbox": [100, 1205, 500, 1240],
            "text": "Figure 1: Sample image",
            "characters": [...]
          }
        },
        {
          "box_id": 3,
          "box_type": "interline_equation",
          "bbox": [200, 1300, 800, 1350],
          "score": 0.91,
          "latex": "E = mc^2",
          "lines": []
        }
      ]
    }
  ]
}
```

---

## 2. 기술 분석

### 2.1 MinerU의 레이아웃 처리 구조

#### 2.1.1 레이아웃 타입 분류
MinerU는 다음과 같은 레이아웃 블록 타입을 감지합니다:

**CategoryId (모델 출력)**:
```python
CategoryId.Title = 0          # 제목
CategoryId.Text = 1           # 일반 텍스트
CategoryId.Abandon = 2        # 버려진 영역 (워터마크 등)
CategoryId.ImageBody = 3      # 이미지 본체
CategoryId.ImageCaption = 4   # 이미지 캡션
CategoryId.TableBody = 5      # 표 본체
CategoryId.TableCaption = 6   # 표 캡션
CategoryId.TableFootnote = 7  # 표 각주
CategoryId.InterlineEquation_Layout = 8   # 행간 수식 (레이아웃)
CategoryId.InlineEquation = 13            # 행내 수식
CategoryId.InterlineEquation_YOLO = 14    # 행간 수식 (YOLO)
CategoryId.OcrText = 15       # OCR 텍스트
CategoryId.ImageFootnote = 101 # 이미지 각주
```

**BlockType (최종 출력)**:
```python
BlockType.TEXT = 'text'
BlockType.TITLE = 'title'
BlockType.IMAGE = 'image'
BlockType.IMAGE_BODY = 'image_body'
BlockType.IMAGE_CAPTION = 'image_caption'
BlockType.IMAGE_FOOTNOTE = 'image_footnote'
BlockType.TABLE = 'table'
BlockType.TABLE_BODY = 'table_body'
BlockType.TABLE_CAPTION = 'table_caption'
BlockType.TABLE_FOOTNOTE = 'table_footnote'
BlockType.INTERLINE_EQUATION = 'interline_equation'
BlockType.CODE = 'code'
BlockType.DISCARDED = 'discarded'
```

#### 2.1.2 표/이미지 블록의 특수 처리

**구조적 차이점**:
1. **텍스트 블록**: 단일 블록으로 처리
2. **표/이미지 블록**: **계층 구조**로 처리
   ```
   IMAGE (그룹)
   ├─ IMAGE_BODY (본체)
   ├─ IMAGE_CAPTION (캡션) - 여러 개 가능
   └─ IMAGE_FOOTNOTE (각주) - 여러 개 가능

   TABLE (그룹)
   ├─ TABLE_BODY (본체)
   ├─ TABLE_CAPTION (캡션)
   └─ TABLE_FOOTNOTE (각주)
   ```

**처리 흐름** (`mineru/backend/pipeline/model_json_to_middle_json.py:28-173`):

```python
# 1. 모델 출력에서 그룹화 (pipeline_magic_model.py:246-282)
img_groups = magic_model.get_imgs()
# img_groups = [
#   {
#     'image_body': {'bbox': [...], 'score': 0.9},
#     'image_caption_list': [{'bbox': [...], 'score': 0.85}, ...],
#     'image_footnote_list': [...]
#   }
# ]

table_groups = magic_model.get_tables()

# 2. 블록으로 변환 (model_json_to_middle_json.py:46-52)
img_body_blocks, img_caption_blocks, img_footnote_blocks, maybe_text_image_blocks =
    process_groups(img_groups, 'image_body', 'image_caption_list', 'image_footnote_list')

# 3. 각 블록에 group_id 할당 (block_pre_proc.py:11-31)
# group_id는 어떤 caption/footnote가 어떤 body에 속하는지 추적용

# 4. span 매핑 (span_block_fix.py:9-41)
# - IMAGE_BODY: ContentType.IMAGE span만 매핑
# - IMAGE_CAPTION: ContentType.TEXT span 매핑
# - TABLE_BODY: ContentType.TABLE span만 매핑
# - TABLE_CAPTION: ContentType.TEXT span 매핑
```

#### 2.1.3 캐릭터 정보 처리 위치

**존재하는 위치**:
```python
# mineru/utils/span_pre_proc.py:212-244
def fill_char_in_spans(spans, all_chars, median_span_height):
    for char in all_chars:
        for span in spans:
            if calculate_char_in_span(char['bbox'], span['bbox'], char['char']):
                span['chars'].append(char)  # ← 여기서 보관됨!
                # char = {
                #   'bbox': [x0, y0, x1, y1],
                #   'char': '책',
                #   'char_idx': 0
                # }
```

**삭제되는 위치**:
```python
# mineru/utils/span_pre_proc.py:286-315
def chars_to_content(span):
    span['chars'] = sorted(span['chars'], key=lambda x: x['char_idx'])
    content = ''
    for char in span['chars']:
        content += char['char']
    span['content'] = content
    del span['chars']  # ← 여기서 삭제됨!
```

#### 2.1.4 표/이미지 내부의 OCR 처리

**표 블록의 OCR**:
```python
# 1. 표 본체 (TABLE_BODY)
# - ContentType.TABLE span이 할당됨
# - 표 인식 모델의 결과가 저장됨:
#   span['html'] = "<table>...</table>"  # HTML 형식
#   span['latex'] = "\\begin{table}..."  # LaTeX 형식
# - 표 내부의 개별 문자는 기본적으로 추출되지 않음

# 2. 표 캡션/각주 (TABLE_CAPTION, TABLE_FOOTNOTE)
# - ContentType.TEXT span이 할당됨
# - 일반 텍스트와 동일하게 char 레벨 정보 추출됨
```

**이미지 블록의 OCR**:
```python
# 1. 이미지 본체 (IMAGE_BODY)
# - ContentType.IMAGE span이 할당됨
# - 이미지는 잘라서 파일로 저장됨:
#   span['image_path'] = "image/abc123_2.jpg"
# - 이미지 내부의 텍스트는 OCR되지 않음 (이미지로 처리)

# 2. 이미지 캡션/각주 (IMAGE_CAPTION, IMAGE_FOOTNOTE)
# - ContentType.TEXT span이 할당됨
# - 일반 텍스트와 동일하게 char 레벨 정보 추출됨
```

**수식 블록의 처리**:
```python
# 1. 행간 수식 (INTERLINE_EQUATION)
# - ContentType.INTERLINE_EQUATION span이 할당됨
# - 수식 인식 모델의 결과가 저장됨:
#   span['content'] = "E = mc^2"  # LaTeX 형식
#   span['latex'] = "E = mc^2"
# - 개별 문자 정보는 없음 (수식 전체가 하나의 span)

# 2. 행내 수식 (INLINE_EQUATION)
# - ContentType.INLINE_EQUATION span이 할당됨
# - 텍스트 라인 내부에 포함됨
# - span['content'] = "\\alpha + \\beta"
```

---

## 3. 구현 방안

### 3.1 아키텍처 설계

#### 3.1.1 새 엔드포인트: `/layout_ocr`

**파일 위치**: `mineru/cli/fast_api.py`

**기존 `/file_parse`와의 차이점**:
| 항목 | `/file_parse` | `/layout_ocr` (신규) |
|------|---------------|----------------------|
| 목적 | Markdown 변환 | 레이아웃 + OCR 정보 |
| 출력 | MD, JSON, ZIP | 구조화된 JSON만 |
| chars 보존 | ❌ 삭제됨 | ✅ 보존됨 |
| 표/이미지 | HTML/LaTeX만 | 구조 + 내부 span 정보 |
| 그룹 정보 | ❌ 없음 | ✅ group_id 보존 |

#### 3.1.2 코드 수정 지점

**1단계: chars 보존 옵션 추가**
```python
# 파일: mineru/utils/span_pre_proc.py
# 위치: 286-315행

def chars_to_content(span, keep_chars=False):
    """
    span의 chars를 content로 변환

    Args:
        span: span 딕셔너리
        keep_chars: True면 chars 정보 보존, False면 삭제
    """
    if len(span['chars']) == 0:
        span['content'] = ''
    else:
        span['chars'] = sorted(span['chars'], key=lambda x: x['char_idx'])
        char_widths = [char['bbox'][2] - char['bbox'][0] for char in span['chars']]
        median_width = statistics.median(char_widths)

        content = ''
        for i, char in enumerate(span['chars']):
            char1 = char
            char2 = span['chars'][i + 1] if i + 1 < len(span['chars']) else None
            if char2 and char2['bbox'][0] - char1['bbox'][2] > median_width * 0.25:
                content += f"{char['char']} "
            else:
                content += char['char']

        content = __replace_unicode(content)
        content = __replace_ligatures(content)
        span['content'] = content.strip()

    if not keep_chars:
        del span['chars']

    return span
```

**2단계: middle_json 생성 시 chars 보존**
```python
# 파일: mineru/backend/pipeline/model_json_to_middle_json.py
# 위치: 176행 (result_to_middle_json 함수)

def result_to_middle_json(model_list, images_list, pdf_doc, image_writer,
                          lang=None, ocr_enable=False, formula_enabled=True,
                          keep_chars=False):  # ← 파라미터 추가
    middle_json = {"pdf_info": [], "_backend":"pipeline", "_version_name": __version__}

    # ... 기존 로직 ...

    # 파일: mineru/utils/span_pre_proc.py:244행 수정
    for span in spans:
        chars_to_content(span, keep_chars=keep_chars)  # ← keep_chars 전달
```

**3단계: 새 엔드포인트 추가**
```python
# 파일: mineru/cli/fast_api.py
# 위치: 새로 추가 (254행 이후)

@app.post(path="/layout_ocr")
async def layout_ocr(
    files: List[UploadFile] = File(...),
    output_dir: str = Form("./output"),
    lang_list: List[str] = Form(["ch"]),
    parse_method: str = Form("auto"),
    start_page_id: int = Form(0),
    end_page_id: int = Form(99999),
):
    """
    레이아웃 박스와 캐릭터 레벨 OCR 정보를 JSON으로 반환

    Returns:
        {
            "status": "success",
            "backend": "pipeline",
            "version": "0.9.0",
            "pages": [...]
        }
    """
    config = getattr(app.state, "config", {})

    try:
        unique_dir = os.path.join(output_dir, str(uuid.uuid4()))
        os.makedirs(unique_dir, exist_ok=True)

        # 파일 처리 (기존과 동일)
        pdf_file_names = []
        pdf_bytes_list = []
        for file in files:
            content = await file.read()
            file_path = Path(file.filename)
            temp_path = Path(unique_dir) / file_path.name
            with open(temp_path, "wb") as f:
                f.write(content)

            file_suffix = guess_suffix_by_path(temp_path)
            if file_suffix in pdf_suffixes + image_suffixes:
                pdf_bytes = read_fn(temp_path)
                pdf_bytes_list.append(pdf_bytes)
                pdf_file_names.append(file_path.stem)
                os.remove(temp_path)

        # 언어 리스트 설정
        actual_lang_list = lang_list
        if len(actual_lang_list) != len(pdf_file_names):
            actual_lang_list = [actual_lang_list[0] if actual_lang_list else "ch"] * len(pdf_file_names)

        # Pipeline 실행 (chars 보존 모드)
        middle_json_list = await aio_layout_ocr_parse(
            output_dir=unique_dir,
            pdf_file_names=pdf_file_names,
            pdf_bytes_list=pdf_bytes_list,
            p_lang_list=actual_lang_list,
            parse_method=parse_method,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            keep_chars=True,  # ← chars 보존!
            **config
        )

        # JSON 변환
        result = format_layout_ocr_result(middle_json_list, pdf_file_names)

        return JSONResponse(
            status_code=200,
            content=result
        )

    except Exception as e:
        logger.exception(e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )
```

**4단계: 결과 포맷팅 함수**
```python
# 파일: mineru/cli/fast_api.py
# 위치: 새로 추가

def format_layout_ocr_result(middle_json_list, pdf_file_names):
    """
    middle_json을 layout_ocr 형식으로 변환

    Args:
        middle_json_list: middle_json 리스트
        pdf_file_names: PDF 파일명 리스트

    Returns:
        포맷팅된 결과 딕셔너리
    """
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

            # preproc_blocks 또는 para_blocks 처리
            blocks = page_info.get("para_blocks") or page_info.get("preproc_blocks", [])

            for block in blocks:
                layout_box = format_block_to_layout_box(block, box_id)
                if layout_box:
                    page_data["layout_boxes"].append(layout_box)
                    box_id += 1

            file_result["pages"].append(page_data)

        result["files"].append(file_result)

    return result


def format_block_to_layout_box(block, box_id):
    """
    block을 layout_box 형식으로 변환

    Args:
        block: preproc_block 또는 para_block
        box_id: 박스 ID

    Returns:
        layout_box 딕셔너리
    """
    block_type = block.get("type")

    # 기본 정보
    layout_box = {
        "box_id": box_id,
        "box_type": block_type,
        "bbox": block.get("bbox"),
    }

    # group_id가 있으면 추가 (표/이미지)
    if "group_id" in block:
        layout_box["group_id"] = block["group_id"]

    # 라인 정보 처리
    lines = block.get("lines", [])
    layout_box["lines"] = []

    for line_idx, line in enumerate(lines):
        line_data = {
            "line_index": line.get("index", line_idx),
            "bbox": line.get("bbox"),
            "spans": []
        }

        # span 정보 처리
        for span in line.get("spans", []):
            span_data = {
                "type": span.get("type"),
                "bbox": span.get("bbox"),
                "score": span.get("score"),
                "content": span.get("content", "")
            }

            # 특수 타입별 추가 정보
            if span.get("type") == "table":
                if "html" in span:
                    span_data["html"] = span["html"]
                if "latex" in span:
                    span_data["latex"] = span["latex"]
            elif span.get("type") == "image":
                if "image_path" in span:
                    span_data["image_path"] = span["image_path"]

            # chars 정보 (있는 경우만)
            if "chars" in span:
                span_data["characters"] = [
                    {
                        "char": char["char"],
                        "bbox": char["bbox"],
                        "char_index": char["char_idx"]
                    }
                    for char in span["chars"]
                ]

            line_data["spans"].append(span_data)

        # 라인 전체 텍스트 생성
        line_text = " ".join(
            span.get("content", "")
            for span in line.get("spans", [])
            if span.get("type") in ["text", "inline_equation"]
        )
        line_data["text"] = line_text.strip()

        layout_box["lines"].append(line_data)

    return layout_box
```

**5단계: aio_layout_ocr_parse 함수 추가**
```python
# 파일: mineru/cli/common.py
# 위치: 새로 추가 (394행 이후)

async def aio_layout_ocr_parse(
    output_dir,
    pdf_file_names: list[str],
    pdf_bytes_list: list[bytes],
    p_lang_list: list[str],
    parse_method="auto",
    start_page_id=0,
    end_page_id=None,
    keep_chars=True,
    **kwargs,
):
    """
    layout_ocr용 파싱 함수 (chars 보존)

    기존 aio_do_parse와 유사하지만:
    1. middle_json만 반환 (파일 저장 안 함)
    2. keep_chars=True로 chars 정보 보존
    """
    from mineru.backend.pipeline.pipeline_analyze import doc_analyze as pipeline_doc_analyze
    from mineru.backend.pipeline.model_json_to_middle_json import result_to_middle_json as pipeline_result_to_middle_json

    # PDF 바이트 전처리
    pdf_bytes_list = _prepare_pdf_bytes(pdf_bytes_list, start_page_id, end_page_id)

    # Pipeline 분석
    infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = (
        pipeline_doc_analyze(
            pdf_bytes_list, p_lang_list, parse_method=parse_method,
            formula_enable=True, table_enable=True
        )
    )

    # middle_json 생성 (chars 보존)
    middle_json_list = []
    for idx, model_list in enumerate(infer_results):
        pdf_file_name = pdf_file_names[idx]
        local_image_dir, local_md_dir = prepare_env(output_dir, pdf_file_name, parse_method)
        image_writer = FileBasedDataWriter(local_image_dir)

        images_list = all_image_lists[idx]
        pdf_doc = all_pdf_docs[idx]
        _lang = lang_list[idx]
        _ocr_enable = ocr_enabled_list[idx]

        middle_json = pipeline_result_to_middle_json(
            model_list, images_list, pdf_doc, image_writer,
            _lang, _ocr_enable, formula_enable=True,
            keep_chars=keep_chars  # ← chars 보존!
        )

        middle_json_list.append(middle_json)

    return middle_json_list
```

---

## 4. 구현 순서

### 4.1 Phase 1: 기본 구조 구현 (2-3시간)
1. ✅ `span_pre_proc.py`의 `chars_to_content()` 함수 수정
2. ✅ `model_json_to_middle_json.py`에 `keep_chars` 파라미터 추가
3. ✅ `common.py`에 `aio_layout_ocr_parse()` 함수 추가
4. ✅ 기본 테스트 (simple text PDF)

### 4.2 Phase 2: 엔드포인트 구현 (1-2시간)
1. ✅ `fast_api.py`에 `/layout_ocr` 엔드포인트 추가
2. ✅ `format_layout_ocr_result()` 함수 구현
3. ✅ `format_block_to_layout_box()` 함수 구현
4. ✅ API 테스트 (Postman/curl)

### 4.3 Phase 3: 특수 케이스 처리 (2-3시간)
1. ✅ 표 블록 처리 (TABLE_BODY, TABLE_CAPTION, TABLE_FOOTNOTE)
2. ✅ 이미지 블록 처리 (IMAGE_BODY, IMAGE_CAPTION, IMAGE_FOOTNOTE)
3. ✅ 수식 블록 처리 (INTERLINE_EQUATION, INLINE_EQUATION)
4. ✅ group_id 기반 블록 그룹핑 정보 포함

### 4.4 Phase 4: 테스트 및 문서화 (1-2시간)
1. ✅ 다양한 PDF 테스트
   - 텍스트만 있는 PDF
   - 표가 있는 PDF
   - 이미지가 있는 PDF
   - 수식이 있는 PDF
   - 복합 레이아웃 PDF
2. ✅ API 문서 작성 (Swagger)
3. ✅ 사용 예제 작성

**총 예상 시간: 6-10시간**

---

## 5. 테스트 계획

### 5.1 유닛 테스트
```python
# tests/test_layout_ocr.py

def test_chars_to_content_with_keep():
    """chars_to_content가 keep_chars=True일 때 chars를 보존하는지 테스트"""
    span = {
        'chars': [
            {'char': 'a', 'bbox': [0, 0, 10, 10], 'char_idx': 0},
            {'char': 'b', 'bbox': [10, 0, 20, 10], 'char_idx': 1}
        ]
    }
    result = chars_to_content(span, keep_chars=True)
    assert 'chars' in result
    assert result['content'] == 'ab'

def test_format_block_to_layout_box():
    """블록이 올바른 layout_box 형식으로 변환되는지 테스트"""
    block = {
        'type': 'text',
        'bbox': [0, 0, 100, 50],
        'lines': [
            {
                'bbox': [0, 0, 100, 25],
                'spans': [
                    {
                        'type': 'text',
                        'bbox': [0, 0, 100, 25],
                        'content': 'Test',
                        'chars': [...]
                    }
                ]
            }
        ]
    }
    result = format_block_to_layout_box(block, 0)
    assert result['box_id'] == 0
    assert result['box_type'] == 'text'
    assert len(result['lines']) == 1
```

### 5.2 통합 테스트
```bash
# 1. 간단한 텍스트 PDF
curl -X POST http://localhost:8000/layout_ocr \
  -F "files=@test_simple.pdf" \
  -F "lang_list=en"

# 2. 표가 있는 PDF
curl -X POST http://localhost:8000/layout_ocr \
  -F "files=@test_table.pdf" \
  -F "lang_list=en" \
  -F "parse_method=auto"

# 3. 이미지가 있는 PDF
curl -X POST http://localhost:8000/layout_ocr \
  -F "files=@test_image.pdf" \
  -F "lang_list=ch"
```

### 5.3 검증 기준
- ✅ 모든 레이아웃 박스가 bbox와 함께 반환됨
- ✅ 텍스트 블록의 chars 정보가 보존됨
- ✅ 표 블록의 HTML/LaTeX가 포함됨
- ✅ 이미지 블록의 image_path가 포함됨
- ✅ group_id로 caption/footnote가 올바르게 연결됨
- ✅ 응답 시간이 기존 `/file_parse`와 유사함

---

## 6. 주의사항 및 제약사항

### 6.1 표 내부의 개별 문자 정보
**현재 상태**:
- 표 인식 모델이 표 전체를 HTML/LaTeX로 변환
- 표 내부의 개별 문자 bbox는 추출되지 않음

**해결 방안** (선택사항):
1. **Option A**: 현재 상태 유지
   - 표는 HTML/LaTeX 형식으로만 제공
   - `table_data.html` / `table_data.latex` 필드에 저장

2. **Option B**: 표 내부 OCR 추가 (추가 개발 필요)
   - 표 영역을 다시 OCR 처리
   - 셀 단위로 텍스트 추출
   - 예상 작업량: +4-6시간

**권장**: Option A (표는 구조화된 형식으로 제공)

### 6.2 이미지 내부의 텍스트
**현재 상태**:
- 이미지 영역은 이미지로 간주
- 내부 텍스트는 OCR되지 않음

**해결 방안** (선택사항):
1. **Option A**: 현재 상태 유지
   - 이미지는 파일로 저장 후 경로만 제공

2. **Option B**: 이미지 내부 OCR 추가 (추가 개발 필요)
   - 이미지 영역을 OCR 처리
   - 별도의 `image_text` 필드로 제공
   - 예상 작업량: +2-3시간

**권장**: Option A

### 6.3 메모리 사용량
**chars 보존으로 인한 메모리 증가**:
- 기존: span당 ~200 bytes (content만)
- 신규: span당 ~500-1000 bytes (chars 배열 포함)
- 증가율: 약 2.5-5배

**완화 방안**:
1. 페이지 단위 처리 (현재 구조)
2. 처리 완료 후 즉시 반환 (파일 저장 안 함)
3. 필요시 pagination 지원

### 6.4 기존 API와의 호환성
**영향 없음**:
- 기존 `/file_parse` 엔드포인트는 그대로 유지
- 새 `/layout_ocr` 엔드포인트는 독립적으로 동작
- 코드 변경은 선택적 파라미터 추가만 (기본값 유지)

---

## 7. API 명세서

### 7.1 엔드포인트
```
POST /layout_ocr
```

### 7.2 Request
```
Content-Type: multipart/form-data

Parameters:
- files: file[] (required)
  - PDF 또는 이미지 파일 (여러 개 가능)

- lang_list: string[] (optional, default: ["ch"])
  - OCR 언어 설정
  - 지원: ch, en, ja, ko, fr, de, es, ru 등

- parse_method: string (optional, default: "auto")
  - auto: 자동 판별
  - ocr: OCR 강제
  - txt: 텍스트 추출만

- output_dir: string (optional, default: "./output")
  - 임시 출력 디렉토리

- start_page_id: integer (optional, default: 0)
  - 시작 페이지 (0-based)

- end_page_id: integer (optional, default: 99999)
  - 종료 페이지 (inclusive)
```

### 7.3 Response (Success)
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
              "lines": [
                {
                  "line_index": 0,
                  "bbox": [169, 429, 894, 466],
                  "text": "책에 바침이란...",
                  "spans": [
                    {
                      "type": "text",
                      "bbox": [169, 429, 894, 466],
                      "score": 0.901,
                      "content": "책에 바침이란...",
                      "characters": [
                        {"char": "책", "bbox": [169, 429, 185, 466], "char_index": 0},
                        {"char": "에", "bbox": [186, 429, 202, 466], "char_index": 1}
                      ]
                    }
                  ]
                }
              ]
            },
            {
              "box_id": 1,
              "box_type": "table",
              "group_id": 0,
              "bbox": [100, 500, 900, 800],
              "lines": [
                {
                  "line_index": 0,
                  "bbox": [105, 505, 895, 540],
                  "text": "",
                  "spans": [
                    {
                      "type": "table",
                      "bbox": [105, 505, 895, 795],
                      "score": 0.92,
                      "content": "",
                      "html": "<table><tr><td>Cell 1</td></tr></table>",
                      "latex": "\\begin{table}...\\end{table}"
                    }
                  ]
                }
              ]
            },
            {
              "box_id": 2,
              "box_type": "image",
              "group_id": 0,
              "bbox": [100, 900, 500, 1200],
              "lines": [
                {
                  "line_index": 0,
                  "bbox": [100, 900, 500, 1200],
                  "text": "",
                  "spans": [
                    {
                      "type": "image",
                      "bbox": [100, 900, 500, 1200],
                      "score": 0.88,
                      "content": "",
                      "image_path": "image/abc123_2.jpg"
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

### 7.4 Response (Error)
```json
{
  "status": "error",
  "message": "Failed to process file: Invalid PDF format"
}
```

### 7.5 HTTP Status Codes
- `200 OK`: 성공
- `400 Bad Request`: 잘못된 요청 (파일 형식 등)
- `500 Internal Server Error`: 서버 오류

---

## 8. 사용 예제

### 8.1 Python
```python
import requests

url = "http://localhost:8000/layout_ocr"

with open("test.pdf", "rb") as f:
    files = {"files": ("test.pdf", f, "application/pdf")}
    data = {
        "lang_list": ["en"],
        "parse_method": "auto"
    }

    response = requests.post(url, files=files, data=data)
    result = response.json()

    # 첫 페이지의 첫 번째 레이아웃 박스
    first_box = result["files"][0]["pages"][0]["layout_boxes"][0]
    print(f"Box type: {first_box['box_type']}")
    print(f"BBox: {first_box['bbox']}")

    # 첫 라인의 문자들
    first_line = first_box["lines"][0]
    for char in first_line["spans"][0]["characters"]:
        print(f"Char: {char['char']}, BBox: {char['bbox']}")
```

### 8.2 cURL
```bash
curl -X POST http://localhost:8000/layout_ocr \
  -F "files=@test.pdf" \
  -F "lang_list=en" \
  -F "parse_method=auto" \
  -F "start_page_id=0" \
  -F "end_page_id=5" \
  | jq '.files[0].pages[0].layout_boxes'
```

### 8.3 JavaScript
```javascript
const formData = new FormData();
formData.append('files', fileInput.files[0]);
formData.append('lang_list', 'en');
formData.append('parse_method', 'auto');

fetch('http://localhost:8000/layout_ocr', {
  method: 'POST',
  body: formData
})
.then(response => response.json())
.then(data => {
  const firstPage = data.files[0].pages[0];
  console.log('Layout boxes:', firstPage.layout_boxes.length);

  firstPage.layout_boxes.forEach(box => {
    console.log(`Box ${box.box_id}: ${box.box_type}`);
    console.log(`  BBox: ${box.bbox}`);

    box.lines.forEach(line => {
      console.log(`  Line: ${line.text}`);
      line.spans.forEach(span => {
        if (span.characters) {
          console.log(`    Characters: ${span.characters.length}`);
        }
      });
    });
  });
});
```

---

## 9. 향후 개선 사항

### 9.1 단기 (1-2주)
- [ ] 페이지네이션 지원 (대용량 PDF)
- [ ] 비동기 처리 (job queue)
- [ ] 진행률 추적 API
- [ ] 결과 캐싱

### 9.2 중기 (1-2개월)
- [ ] 표 내부 셀 단위 OCR
- [ ] 이미지 내부 텍스트 OCR
- [ ] 레이아웃 신뢰도 점수
- [ ] Bounding box 시각화 API

### 9.3 장기 (3-6개월)
- [ ] WebSocket 실시간 스트리밍
- [ ] 배치 처리 최적화
- [ ] GPU 메모리 최적화
- [ ] 다중 언어 혼합 문서 처리

---

## 10. 참고 자료

### 10.1 관련 파일
- `mineru/cli/fast_api.py` - FastAPI 엔드포인트
- `mineru/cli/common.py` - 파싱 로직
- `mineru/backend/pipeline/pipeline_analyze.py` - 레이아웃 분석
- `mineru/backend/pipeline/model_json_to_middle_json.py` - JSON 변환
- `mineru/utils/span_pre_proc.py` - Span 전처리
- `mineru/utils/span_block_fix.py` - Span-Block 매핑
- `mineru/utils/block_pre_proc.py` - Block 전처리
- `mineru/utils/draw_bbox.py` - BBox 시각화

### 10.2 주요 데이터 구조
```python
# layout_dets (모델 출력)
{
  'category_id': int,      # CategoryId enum
  'bbox': [x0, y0, x1, y1],
  'score': float,
  'poly': [x0, y0, x0, y1, x1, y1, x1, y0],
  'text': str,            # OcrText인 경우
  'latex': str,           # 수식인 경우
  'html': str,            # 표인 경우
}

# span (중간 표현)
{
  'type': str,            # ContentType
  'bbox': [x0, y0, x1, y1],
  'score': float,
  'content': str,
  'chars': [              # 텍스트인 경우만
    {
      'char': str,
      'bbox': [x0, y0, x1, y1],
      'char_idx': int
    }
  ]
}

# block (최종 표현)
{
  'type': str,            # BlockType
  'bbox': [x0, y0, x1, y1],
  'group_id': int,        # 표/이미지인 경우
  'lines': [
    {
      'bbox': [x0, y0, x1, y1],
      'index': int,
      'spans': [...]
    }
  ]
}
```

---

## 11. 결론

MinerU는 이미 내부적으로 캐릭터 레벨 OCR 정보를 수집하고 있으며, 표/이미지/수식 등의 복잡한 레이아웃도 bbox와 함께 감지하고 있습니다.

**핵심 발견**:
1. ✅ 모든 레이아웃 타입이 bbox로 감지됨 (텍스트, 표, 이미지, 수식)
2. ✅ 캐릭터 정보가 이미 추출되고 있음 (단지 삭제될 뿐)
3. ✅ 표/이미지는 계층 구조로 처리됨 (body + caption + footnote)
4. ✅ group_id로 관계 추적 가능

따라서 요구사항을 충족하는 API 구현은 **완전히 가능**하며, 예상 작업량은 **6-10시간** 정도입니다. 기존 파이프라인을 거의 변경하지 않고 단순히 중간 결과를 보존하는 방식으로 구현 가능합니다.

**다음 단계**:
1. Phase 1부터 순차적으로 구현 시작
2. 각 Phase 완료 후 테스트
3. 최종 통합 테스트 및 문서화
