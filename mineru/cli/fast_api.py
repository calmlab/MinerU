import uuid
import os
import re
import tempfile
import asyncio
import uvicorn
import click
import zipfile
from pathlib import Path
import glob
from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, FileResponse
from starlette.background import BackgroundTask
from typing import List, Optional
from loguru import logger
from base64 import b64encode

from mineru.cli.common import aio_do_parse, read_fn, pdf_suffixes, image_suffixes
from mineru.cli.layout_ocr_helper import aio_layout_ocr_parse, format_layout_ocr_result
from mineru.cli.layout_ocr_streaming import stream_layout_ocr_pages
from mineru.utils.cli_parser import arg_parse
from mineru.utils.guess_suffix_or_lang import guess_suffix_by_path
from mineru.version import __version__

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)


def sanitize_filename(filename: str) -> str:
    """
    格式化压缩文件的文件名
    移除路径遍历字符, 保留 Unicode 字母、数字、._- 
    禁止隐藏文件
    """
    sanitized = re.sub(r'[/\\\.]{2,}|[/\\]', '', filename)
    sanitized = re.sub(r'[^\w.-]', '_', sanitized, flags=re.UNICODE)
    if sanitized.startswith('.'):
        sanitized = '_' + sanitized[1:]
    return sanitized or 'unnamed'

def cleanup_file(file_path: str) -> None:
    """清理临时 zip 文件"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.warning(f"fail clean file {file_path}: {e}")

def encode_image(image_path: str) -> str:
    """Encode image using base64"""
    with open(image_path, "rb") as f:
        return b64encode(f.read()).decode()


def get_infer_result(file_suffix_identifier: str, pdf_name: str, parse_dir: str) -> Optional[str]:
    """从结果文件中读取推理结果"""
    result_file_path = os.path.join(parse_dir, f"{pdf_name}{file_suffix_identifier}")
    if os.path.exists(result_file_path):
        with open(result_file_path, "r", encoding="utf-8") as fp:
            return fp.read()
    return None


@app.post(path="/file_parse",)
async def parse_pdf(
        files: List[UploadFile] = File(...),
        output_dir: str = Form("./output"),
        lang_list: List[str] = Form(["ch"]),
        backend: str = Form("pipeline"),
        parse_method: str = Form("auto"),
        formula_enable: bool = Form(True),
        table_enable: bool = Form(True),
        server_url: Optional[str] = Form(None),
        return_md: bool = Form(True),
        return_middle_json: bool = Form(False),
        return_model_output: bool = Form(False),
        return_content_list: bool = Form(False),
        return_images: bool = Form(False),
        response_format_zip: bool = Form(False),
        start_page_id: int = Form(0),
        end_page_id: int = Form(99999),
):

    # 获取命令行配置参数
    config = getattr(app.state, "config", {})

    try:
        # 创建唯一的输出目录
        unique_dir = os.path.join(output_dir, str(uuid.uuid4()))
        os.makedirs(unique_dir, exist_ok=True)

        # 处理上传的PDF文件
        pdf_file_names = []
        pdf_bytes_list = []

        for file in files:
            content = await file.read()
            file_path = Path(file.filename)

            # 创建临时文件
            temp_path = Path(unique_dir) / file_path.name
            with open(temp_path, "wb") as f:
                f.write(content)

            # 如果是图像文件或PDF，使用read_fn处理
            file_suffix = guess_suffix_by_path(temp_path)
            if file_suffix in pdf_suffixes + image_suffixes:
                try:
                    pdf_bytes = read_fn(temp_path)
                    pdf_bytes_list.append(pdf_bytes)
                    pdf_file_names.append(file_path.stem)
                    os.remove(temp_path)  # 删除临时文件
                except Exception as e:
                    return JSONResponse(
                        status_code=400,
                        content={"error": f"Failed to load file: {str(e)}"}
                    )
            else:
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Unsupported file type: {file_suffix}"}
                )


        # 设置语言列表，确保与文件数量一致
        actual_lang_list = lang_list
        if len(actual_lang_list) != len(pdf_file_names):
            # 如果语言列表长度不匹配，使用第一个语言或默认"ch"
            actual_lang_list = [actual_lang_list[0] if actual_lang_list else "ch"] * len(pdf_file_names)

        # 调用异步处理函数
        await aio_do_parse(
            output_dir=unique_dir,
            pdf_file_names=pdf_file_names,
            pdf_bytes_list=pdf_bytes_list,
            p_lang_list=actual_lang_list,
            backend=backend,
            parse_method=parse_method,
            formula_enable=formula_enable,
            table_enable=table_enable,
            server_url=server_url,
            f_draw_layout_bbox=False,
            f_draw_span_bbox=False,
            f_dump_md=return_md,
            f_dump_middle_json=return_middle_json,
            f_dump_model_output=return_model_output,
            f_dump_orig_pdf=False,
            f_dump_content_list=return_content_list,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            **config
        )

        # 根据 response_format_zip 决定返回类型
        if response_format_zip:
            zip_fd, zip_path = tempfile.mkstemp(suffix=".zip", prefix="mineru_results_")
            os.close(zip_fd) 
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for pdf_name in pdf_file_names:
                    safe_pdf_name = sanitize_filename(pdf_name)
                    if backend.startswith("pipeline"):
                        parse_dir = os.path.join(unique_dir, pdf_name, parse_method)
                    else:
                        parse_dir = os.path.join(unique_dir, pdf_name, "vlm")

                    if not os.path.exists(parse_dir):
                        continue

                    # 写入文本类结果
                    if return_md:
                        path = os.path.join(parse_dir, f"{pdf_name}.md")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}.md"))

                    if return_middle_json:
                        path = os.path.join(parse_dir, f"{pdf_name}_middle.json")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_middle.json"))

                    if return_model_output:
                        if backend.startswith("pipeline"):
                            path = os.path.join(parse_dir, f"{pdf_name}_model.json")
                        else:
                            path = os.path.join(parse_dir, f"{pdf_name}_model_output.txt")
                        if os.path.exists(path): 
                            zf.write(path, arcname=os.path.join(safe_pdf_name, os.path.basename(path)))

                    if return_content_list:
                        path = os.path.join(parse_dir, f"{pdf_name}_content_list.json")
                        if os.path.exists(path):
                            zf.write(path, arcname=os.path.join(safe_pdf_name, f"{safe_pdf_name}_content_list.json"))

                    # 写入图片
                    if return_images:
                        images_dir = os.path.join(parse_dir, "images")
                        image_paths = glob.glob(os.path.join(glob.escape(images_dir), "*.jpg"))
                        for image_path in image_paths:
                            zf.write(image_path, arcname=os.path.join(safe_pdf_name, "images", os.path.basename(image_path)))

            return FileResponse(
                path=zip_path,
                media_type="application/zip",
                filename="results.zip",
                background=BackgroundTask(cleanup_file, zip_path)
            )
        else:
            # 构建 JSON 结果
            result_dict = {}
            for pdf_name in pdf_file_names:
                result_dict[pdf_name] = {}
                data = result_dict[pdf_name]

                if backend.startswith("pipeline"):
                    parse_dir = os.path.join(unique_dir, pdf_name, parse_method)
                else:
                    parse_dir = os.path.join(unique_dir, pdf_name, "vlm")

                if os.path.exists(parse_dir):
                    if return_md:
                        data["md_content"] = get_infer_result(".md", pdf_name, parse_dir)
                    if return_middle_json:
                        data["middle_json"] = get_infer_result("_middle.json", pdf_name, parse_dir)
                    if return_model_output:
                        if backend.startswith("pipeline"):
                            data["model_output"] = get_infer_result("_model.json", pdf_name, parse_dir)
                        else:
                            data["model_output"] = get_infer_result("_model_output.txt", pdf_name, parse_dir)
                    if return_content_list:
                        data["content_list"] = get_infer_result("_content_list.json", pdf_name, parse_dir)
                    if return_images:
                        images_dir = os.path.join(parse_dir, "images")
                        safe_pattern = os.path.join(glob.escape(images_dir), "*.jpg")
                        image_paths = glob.glob(safe_pattern)
                        data["images"] = {
                            os.path.basename(
                                image_path
                            ): f"data:image/jpeg;base64,{encode_image(image_path)}"
                            for image_path in image_paths
                        }

            return JSONResponse(
                status_code=200,
                content={
                    "backend": backend,
                    "version": __version__,
                    "results": result_dict
                }
            )
    except Exception as e:
        logger.exception(e)
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to process file: {str(e)}"}
        )


@app.post(path="/layout_ocr")
async def layout_ocr(
    files: List[UploadFile] = File(...),
    output_dir: str = Form("./output"),
    lang_list: List[str] = Form(["ch"]),
    parse_method: str = Form("auto"),
    include_discarded: bool = Form(False),
    start_page_id: int = Form(0),
    end_page_id: int = Form(99999),
):
    """
    Layout OCR API Endpoint

    Returns layout boxes with character-level OCR information including bbox coordinates.

    Parameters:
    - files: PDF or image files (multiple files supported)
    - output_dir: Temporary output directory
    - lang_list: OCR languages (ch, en, ja, ko, etc.)
    - parse_method: Parsing method (auto/ocr/txt)
    - include_discarded: Whether to include discarded blocks (headers/footers)
    - start_page_id: Start page index (0-based)
    - end_page_id: End page index (inclusive)

    Returns:
    JSON with layout boxes, bboxes, and character information
    """
    config = getattr(app.state, "config", {})

    try:
        # Create unique output directory
        unique_dir = os.path.join(output_dir, str(uuid.uuid4()))
        os.makedirs(unique_dir, exist_ok=True)

        # Process uploaded files
        pdf_file_names = []
        pdf_bytes_list = []

        for file in files:
            content = await file.read()
            file_path = Path(file.filename)

            # Create temporary file
            temp_path = Path(unique_dir) / file_path.name
            with open(temp_path, "wb") as f:
                f.write(content)

            # Check file type
            file_suffix = guess_suffix_by_path(temp_path)
            if file_suffix in pdf_suffixes + image_suffixes:
                try:
                    pdf_bytes = read_fn(temp_path)
                    pdf_bytes_list.append(pdf_bytes)
                    pdf_file_names.append(file_path.stem)
                    os.remove(temp_path)  # Clean up temp file
                except Exception as e:
                    return JSONResponse(
                        status_code=400,
                        content={"status": "error", "message": f"Failed to load file: {str(e)}"}
                    )
            else:
                return JSONResponse(
                    status_code=400,
                    content={"status": "error", "message": f"Unsupported file type: {file_suffix}"}
                )

        # Set language list
        actual_lang_list = lang_list
        if len(actual_lang_list) != len(pdf_file_names):
            actual_lang_list = [actual_lang_list[0] if actual_lang_list else "ch"] * len(pdf_file_names)

        # Call layout_ocr parsing pipeline
        logger.info(f"Processing {len(pdf_file_names)} file(s) with layout_ocr pipeline...")
        middle_json_list = await aio_layout_ocr_parse(
            output_dir=unique_dir,
            pdf_file_names=pdf_file_names,
            pdf_bytes_list=pdf_bytes_list,
            p_lang_list=actual_lang_list,
            parse_method=parse_method,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            **config
        )

        # Format result
        result = format_layout_ocr_result(
            middle_json_list,
            pdf_file_names,
            include_discarded=include_discarded
        )

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


@app.websocket("/layout_ocr/stream")
async def layout_ocr_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for page-by-page streaming of layout OCR results.

    Protocol:
    1. Client connects to WebSocket
    2. Client sends JSON with parameters:
       {
           "pdf_base64": "...",
           "filename": "document.pdf",
           "lang": "ko",
           "parse_method": "auto",
           "include_discarded": false,
           "start_page_id": 0,
           "end_page_id": 99999
       }
    3. Server streams back JSON messages per page
    4. Client can disconnect anytime
    """
    await websocket.accept()
    config = getattr(app.state, "config", {})

    try:
        # Receive parameters from client
        data = await websocket.receive_json()

        # Extract parameters
        pdf_base64 = data.get("pdf_base64")
        filename = data.get("filename", "document.pdf")
        lang = data.get("lang", "ch")
        parse_method = data.get("parse_method", "auto")
        include_discarded = data.get("include_discarded", False)
        start_page_id = data.get("start_page_id", 0)
        end_page_id = data.get("end_page_id", 99999)
        output_dir = data.get("output_dir", "./output")

        # Decode PDF
        import base64
        if pdf_base64:
            pdf_bytes = base64.b64decode(pdf_base64)
        else:
            # Alternative: receive bytes directly
            pdf_bytes = await websocket.receive_bytes()

        # Validate file type
        pdf_filename = Path(filename).stem

        # Stream processing
        await stream_layout_ocr_pages(
            websocket=websocket,
            pdf_bytes=pdf_bytes,
            pdf_filename=pdf_filename,
            lang=lang,
            parse_method=parse_method,
            include_discarded=include_discarded,
            start_page_id=start_page_id,
            end_page_id=end_page_id,
            output_dir=output_dir,
            **config
        )

    except WebSocketDisconnect:
        logger.info("Client disconnected from WebSocket")
    except Exception as e:
        logger.exception(e)
        try:
            await websocket.send_json({
                "status": "error",
                "message": str(e)
            })
        except:
            pass


@click.command(context_settings=dict(ignore_unknown_options=True, allow_extra_args=True))
@click.pass_context
@click.option('--host', default='127.0.0.1', help='Server host (default: 127.0.0.1)')
@click.option('--port', default=8000, type=int, help='Server port (default: 8000)')
@click.option('--reload', is_flag=True, help='Enable auto-reload (development mode)')
def main(ctx, host, port, reload, **kwargs):

    kwargs.update(arg_parse(ctx))

    # 将配置参数存储到应用状态中
    app.state.config = kwargs

    """启动MinerU FastAPI服务器的命令行入口"""
    print(f"Start MinerU FastAPI Service: http://{host}:{port}")
    print("The API documentation can be accessed at the following address:")
    print(f"- Swagger UI: http://{host}:{port}/docs")
    print(f"- ReDoc: http://{host}:{port}/redoc")

    uvicorn.run(
        "mineru.cli.fast_api:app",
        host=host,
        port=port,
        reload=reload
    )


if __name__ == "__main__":
    main()