"""
Layout OCR WebSocket Streaming Module

Provides page-by-page streaming of layout OCR results via WebSocket.
Designed for client servers that process pages in parallel.
"""

import os
import uuid
from pathlib import Path
from typing import Optional
from loguru import logger

from mineru.backend.pipeline.pipeline_analyze import doc_analyze
from mineru.backend.pipeline.model_json_to_middle_json import (
    page_model_info_to_page_info,
    make_page_info_dict
)
from mineru.cli.common import prepare_env, _prepare_pdf_bytes, read_fn
from mineru.cli.layout_ocr_helper import (
    restore_chars_to_middle_json,
    format_block_to_layout_box
)
from mineru.data.data_reader_writer import FileBasedDataWriter
from mineru.utils.guess_suffix_or_lang import guess_suffix_by_path
from mineru.version import __version__


async def stream_layout_ocr_pages(
    websocket,
    pdf_bytes: bytes,
    pdf_filename: str,
    lang: str = "ch",
    parse_method: str = "auto",
    include_discarded: bool = False,
    start_page_id: int = 0,
    end_page_id: Optional[int] = None,
    output_dir: str = "./output",
    **kwargs
):
    """
    Stream layout OCR results page by page via WebSocket.

    Args:
        websocket: FastAPI WebSocket connection
        pdf_bytes: PDF file bytes
        pdf_filename: PDF filename (without extension)
        lang: OCR language
        parse_method: Parsing method (auto/ocr/txt)
        include_discarded: Whether to include discarded blocks
        start_page_id: Start page index
        end_page_id: End page index
        output_dir: Temporary output directory
        **kwargs: Additional config parameters

    Sends JSON messages:
    1. {"status": "started", "total_pages": N}
    2. {"status": "processing", "page_index": i, "progress": 0.5, "data": {...}}
    3. {"status": "completed", "total_pages": N}
    4. {"status": "error", "message": "..."}
    """
    try:
        # Create unique output directory
        unique_dir = os.path.join(output_dir, str(uuid.uuid4()))
        os.makedirs(unique_dir, exist_ok=True)

        # Prepare PDF bytes
        pdf_bytes_list = _prepare_pdf_bytes([pdf_bytes], start_page_id, end_page_id)

        # Send start message
        await websocket.send_json({
            "status": "started",
            "message": "Starting layout analysis..."
        })

        # Run pipeline analysis (batch processing for all pages)
        logger.info("Running layout analysis with MinerU pipeline...")
        infer_results, all_image_lists, all_pdf_docs, lang_list, ocr_enabled_list = doc_analyze(
            pdf_bytes_list, [lang], parse_method=parse_method,
            formula_enable=True, table_enable=True
        )

        # Get results for single PDF
        model_list = infer_results[0]
        images_list = all_image_lists[0]
        pdf_doc = all_pdf_docs[0]
        _lang = lang_list[0]
        _ocr_enable = ocr_enabled_list[0]

        total_pages = len(model_list)

        # Send total pages info
        await websocket.send_json({
            "status": "analyzing",
            "total_pages": total_pages,
            "message": f"Processing {total_pages} pages..."
        })

        # Setup image writer
        local_image_dir, local_md_dir = prepare_env(unique_dir, pdf_filename, parse_method)
        image_writer = FileBasedDataWriter(local_image_dir)

        # Process and stream each page
        for page_index, page_model_info in enumerate(model_list):
            try:
                # Process single page
                page = pdf_doc[page_index]
                image_dict = images_list[page_index]

                page_info = page_model_info_to_page_info(
                    page_model_info, image_dict, page, image_writer,
                    page_index, ocr_enable=_ocr_enable, formula_enabled=True
                )

                if page_info is None:
                    page_w, page_h = map(int, page.get_size())
                    page_info = make_page_info_dict([], page_index, page_w, page_h, [])

                # Create mini middle_json for this page
                page_middle_json = {
                    "pdf_info": [page_info],
                    "_backend": "pipeline",
                    "_version_name": __version__
                }

                # Restore chars for this page
                page_middle_json = restore_chars_to_middle_json(page_middle_json, pdf_doc)

                # Format page result
                page_data = format_page_result(
                    page_middle_json["pdf_info"][0],
                    include_discarded=include_discarded
                )

                # Calculate progress
                progress = (page_index + 1) / total_pages

                # Send page result
                await websocket.send_json({
                    "status": "processing",
                    "page_index": page_index,
                    "total_pages": total_pages,
                    "progress": round(progress, 3),
                    "data": page_data
                })

                logger.info(f"Streamed page {page_index + 1}/{total_pages}")

            except Exception as e:
                logger.error(f"Error processing page {page_index}: {e}")
                await websocket.send_json({
                    "status": "page_error",
                    "page_index": page_index,
                    "message": str(e)
                })
                continue

        # Send completion message
        await websocket.send_json({
            "status": "completed",
            "total_pages": total_pages,
            "message": "All pages processed successfully"
        })

        # Cleanup
        pdf_doc.close()

    except Exception as e:
        logger.exception(e)
        await websocket.send_json({
            "status": "error",
            "message": str(e)
        })


def format_page_result(page_info: dict, include_discarded: bool = False) -> dict:
    """
    Format a single page_info to API response format.

    Args:
        page_info: Single page info from middle_json
        include_discarded: Whether to include discarded blocks

    Returns:
        Formatted page data dictionary
    """
    page_data = {
        "page_index": page_info["page_idx"],
        "page_size": {
            "width": page_info["page_size"][0],
            "height": page_info["page_size"][1]
        },
        "layout_boxes": []
    }

    box_id = 0

    # Process main blocks
    blocks = page_info.get("para_blocks") or page_info.get("preproc_blocks", [])
    for block in blocks:
        layout_box = format_block_to_layout_box(block, box_id)
        if layout_box:
            page_data["layout_boxes"].append(layout_box)
            box_id += 1

    # Process discarded blocks if requested
    if include_discarded:
        page_data["discarded_boxes"] = []
        for block in page_info.get("discarded_blocks", []):
            layout_box = format_block_to_layout_box(block, box_id)
            if layout_box:
                layout_box["is_discarded"] = True
                page_data["discarded_boxes"].append(layout_box)
                box_id += 1

    return page_data
