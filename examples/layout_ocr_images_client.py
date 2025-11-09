#!/usr/bin/env python3
"""
Layout OCR Images API Client Example

This client demonstrates the /layout_ocr_images endpoint which accepts
page images directly instead of PDFs.

Usage:
    # Process page images directly
    python layout_ocr_images_client.py page_0.jpg page_1.jpg page_2.jpg

    # Convert PDF to images first, then process
    python layout_ocr_images_client.py document.pdf --convert-pdf --lang ko

    # Custom server
    python layout_ocr_images_client.py *.jpg --server http://192.168.1.100:8000
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

try:
    import requests
    import fitz  # PyMuPDF
    from PIL import Image
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.panel import Panel
except ImportError:
    print("Required packages not installed. Installing...")
    os.system("pip install requests PyMuPDF Pillow rich")
    import requests
    import fitz
    from PIL import Image
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table
    from rich.panel import Panel

console = Console()


def pdf_to_images(pdf_path, output_dir="temp_images"):
    """Convert PDF pages to image files."""
    console.print(f"[cyan]→[/cyan] Converting PDF to images...")

    Path(output_dir).mkdir(exist_ok=True)

    doc = fitz.open(pdf_path)
    image_files = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]

        # Render at 2x scale for quality
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))

        # Convert to PIL Image
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # Save as JPG
        output_path = Path(output_dir) / f"page_{page_idx:04d}.jpg"
        img.save(output_path, "JPEG", quality=95)
        image_files.append(str(output_path))

        console.print(f"  [green]✓[/green] Page {page_idx}: {output_path}")

    doc.close()
    console.print(f"[green]✓[/green] Created {len(image_files)} image files\n")

    return image_files, output_dir


def validate_images(image_paths):
    """Validate that all paths are valid image files."""
    valid_images = []

    for img_path in image_paths:
        path = Path(img_path)

        if not path.exists():
            console.print(f"[yellow]⚠[/yellow] File not found: {img_path}")
            continue

        # Check if it's an image by trying to open it
        try:
            with Image.open(path) as img:
                valid_images.append(str(path))
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] Not a valid image: {img_path} ({e})")
            continue

    return valid_images


def print_page_summary(page_data):
    """Print summary of a single page."""
    page_idx = page_data.get('page_index', 'N/A')
    page_size = page_data.get('page_size', {})
    layout_boxes = page_data.get('layout_boxes', [])
    discarded_boxes = page_data.get('discarded_boxes', [])

    # Count by box type
    box_types = {}
    for box in layout_boxes:
        box_type = box.get('box_type', 'unknown')
        box_types[box_type] = box_types.get(box_type, 0) + 1

    # Count total characters
    total_chars = 0
    for box in layout_boxes:
        for line in box.get('lines', []):
            for span in line.get('spans', []):
                chars = span.get('characters', [])
                total_chars += len(chars)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Page", f"#{page_idx}")
    table.add_row("Size", f"{page_size.get('width', 0)} x {page_size.get('height', 0)}")
    table.add_row("Layout Boxes", str(len(layout_boxes)))
    if discarded_boxes:
        table.add_row("Discarded", str(len(discarded_boxes)))
    table.add_row("Characters", str(total_chars))

    if box_types:
        box_type_str = ", ".join([f"{k}:{v}" for k, v in box_types.items()])
        table.add_row("Types", box_type_str)

    console.print(table)


def process_images(image_paths, server_url, lang, include_discarded):
    """Process images using /layout_ocr_images API."""
    console.print(Panel.fit(
        "[bold cyan]/layout_ocr_images API[/bold cyan]",
        border_style="cyan"
    ))

    url = f"{server_url}/layout_ocr_images"

    console.print(f"[cyan]→[/cyan] Server: {url}")
    console.print(f"[cyan]→[/cyan] Images: {len(image_paths)}")
    console.print(f"[cyan]→[/cyan] Language: {lang}")
    console.print(f"[cyan]→[/cyan] Include discarded: {include_discarded}\n")

    start_time = time.time()

    try:
        # Prepare files
        files = []
        for img_path in image_paths:
            files.append(('images', (Path(img_path).name, open(img_path, 'rb'), 'image/jpeg')))

        # Prepare form data
        data = {
            'lang_list': [lang] * len(image_paths),
            'parse_method': 'auto',
            'include_discarded': str(include_discarded).lower()
        }

        console.print("[cyan]→[/cyan] Uploading images...")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Processing...", total=None)

            response = requests.post(url, files=files, data=data, timeout=600)

            progress.update(task, completed=True)

        # Close file handles
        for _, (_, file_handle, _) in files:
            file_handle.close()

        elapsed = time.time() - start_time

        if response.status_code == 200:
            result = response.json()

            console.print(f"\n[green]✓[/green] Processing completed in {elapsed:.1f}s")

            # Print summary
            if result.get('status') == 'success':
                files_data = result.get('files', [])
                if files_data:
                    file_data = files_data[0]
                    pages = file_data.get('pages', [])

                    console.print(f"\n[bold]Summary:[/bold]")
                    console.print(f"  Total pages: {len(pages)}")
                    console.print(f"  Backend: {result.get('backend', 'N/A')}")
                    console.print(f"  Version: {result.get('version', 'N/A')}")

                    # Sample first page
                    if pages:
                        console.print(f"\n[bold]First Page Sample:[/bold]")
                        print_page_summary(pages[0])

            return result
        else:
            console.print(f"[red]Error:[/red] Server returned {response.status_code}")
            console.print(f"[red]Message:[/red] {response.text}")
            return None

    except requests.exceptions.Timeout:
        console.print("[red]Error:[/red] Request timeout (>600s)")
        return None
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        import traceback
        traceback.print_exc()
        return None


def save_result_to_file(result, output_path):
    """Save processing result to JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    console.print(f"[green]✓[/green] Result saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Layout OCR Images API Client',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process image files directly
  python layout_ocr_images_client.py page_0.jpg page_1.jpg page_2.jpg

  # Process all JPG files in current directory
  python layout_ocr_images_client.py *.jpg

  # Convert PDF to images first, then process
  python layout_ocr_images_client.py document.pdf --convert-pdf --lang ko

  # Custom server
  python layout_ocr_images_client.py *.jpg --server http://192.168.1.100:8000

  # Include discarded blocks (headers/footers)
  python layout_ocr_images_client.py *.jpg --include-discarded
        """
    )

    parser.add_argument(
        'input_paths',
        nargs='+',
        help='Image file paths or PDF path (with --convert-pdf)'
    )
    parser.add_argument(
        '--convert-pdf',
        action='store_true',
        help='Convert PDF to images first'
    )
    parser.add_argument(
        '--server',
        default='http://localhost:8000',
        help='Server URL (default: http://localhost:8000)'
    )
    parser.add_argument(
        '--lang',
        default='ch',
        help='OCR language (default: ch, options: ch, en, ja, ko, etc.)'
    )
    parser.add_argument(
        '--include-discarded',
        action='store_true',
        help='Include discarded blocks (headers/footers)'
    )
    parser.add_argument(
        '--output',
        help='Output JSON file path (default: auto-generated)'
    )
    parser.add_argument(
        '--keep-images',
        action='store_true',
        help='Keep temporary image files after processing (when using --convert-pdf)'
    )

    args = parser.parse_args()

    console.print(f"\n[bold]Layout OCR Images Client[/bold]\n")

    # Determine image files
    temp_dir = None

    if args.convert_pdf:
        # Convert PDF to images mode
        if len(args.input_paths) != 1:
            console.print("[red]Error:[/red] --convert-pdf requires exactly one PDF file")
            sys.exit(1)

        pdf_path = args.input_paths[0]
        if not os.path.exists(pdf_path):
            console.print(f"[red]Error:[/red] File not found: {pdf_path}")
            sys.exit(1)

        image_files, temp_dir = pdf_to_images(pdf_path)
    else:
        # Direct image files mode
        console.print(f"[cyan]→[/cyan] Validating {len(args.input_paths)} image file(s)...")
        image_files = validate_images(args.input_paths)

        if not image_files:
            console.print("[red]Error:[/red] No valid image files found")
            sys.exit(1)

        console.print(f"[green]✓[/green] Found {len(image_files)} valid image(s)\n")

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        if args.convert_pdf:
            base_name = Path(args.input_paths[0]).stem
        else:
            base_name = "images"
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"{base_name}_layout_ocr_images_{timestamp}.json"

    # Process images
    result = process_images(
        image_files,
        args.server,
        args.lang,
        args.include_discarded
    )

    # Cleanup temporary images if needed
    if temp_dir and not args.keep_images:
        console.print(f"\n[cyan]→[/cyan] Cleaning up temporary images...")
        for img_file in image_files:
            if Path(img_file).exists():
                Path(img_file).unlink()

        if Path(temp_dir).exists():
            try:
                Path(temp_dir).rmdir()
                console.print(f"[green]✓[/green] Removed temporary directory: {temp_dir}")
            except:
                console.print(f"[yellow]⚠[/yellow] Could not remove directory: {temp_dir}")

    # Save result
    if result:
        console.print()
        save_result_to_file(result, output_path)

        # Print final statistics
        console.print(f"\n[bold]Final Statistics:[/bold]")
        if result.get('files'):
            total_pages = len(result['files'][0].get('pages', []))
            total_boxes = sum(
                len(page.get('layout_boxes', []))
                for page in result['files'][0].get('pages', [])
            )
            total_chars = sum(
                sum(
                    len(span.get('characters', []))
                    for line in box.get('lines', [])
                    for span in line.get('spans', [])
                )
                for page in result['files'][0].get('pages', [])
                for box in page.get('layout_boxes', [])
            )

            stats_table = Table(show_header=False, box=None)
            stats_table.add_column("Metric", style="cyan")
            stats_table.add_column("Value", style="white", justify="right")

            stats_table.add_row("Total Pages", str(total_pages))
            stats_table.add_row("Total Layout Boxes", str(total_boxes))
            stats_table.add_row("Total Characters", str(total_chars))

            console.print(stats_table)

        console.print(f"\n[green]✓[/green] All done!")
    else:
        console.print(f"\n[red]✗[/red] Processing failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
