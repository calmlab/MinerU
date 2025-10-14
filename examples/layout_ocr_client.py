#!/usr/bin/env python3
"""
Layout OCR API Client Example

Supports both HTTP batch processing and WebSocket streaming.

Usage:
    # HTTP batch processing
    python layout_ocr_client.py document.pdf --mode http --lang ko

    # WebSocket streaming
    python layout_ocr_client.py document.pdf --mode websocket --lang ko

    # With custom server
    python layout_ocr_client.py document.pdf --mode websocket --server http://192.168.1.100:8000
"""

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

try:
    import requests
    import websockets
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.panel import Panel
except ImportError:
    print("Required packages not installed. Installing...")
    os.system("pip install requests websockets rich")
    import requests
    import websockets
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.table import Table
    from rich.panel import Panel

console = Console()


def save_result_to_file(result, output_path):
    """Save processing result to JSON file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    console.print(f"[green]✓[/green] Result saved to: {output_path}")


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


def process_http_batch(pdf_path, server_url, lang, include_discarded, start_page=0, end_page=99999):
    """Process PDF using HTTP batch API."""
    console.print(Panel.fit(
        "[bold cyan]HTTP Batch Processing Mode[/bold cyan]",
        border_style="cyan"
    ))

    if not os.path.exists(pdf_path):
        console.print(f"[red]Error:[/red] File not found: {pdf_path}")
        return None

    url = f"{server_url}/layout_ocr"

    console.print(f"[cyan]→[/cyan] Uploading PDF: {pdf_path}")
    console.print(f"[cyan]→[/cyan] Server: {url}")
    console.print(f"[cyan]→[/cyan] Language: {lang}")
    if end_page < 99999:
        console.print(f"[cyan]→[/cyan] Page range: {start_page} - {end_page}")

    start_time = time.time()

    try:
        with open(pdf_path, 'rb') as f:
            files = {'files': (Path(pdf_path).name, f, 'application/pdf')}
            data = {
                'lang_list': lang,
                'parse_method': 'auto',
                'include_discarded': str(include_discarded).lower(),
                'start_page_id': str(start_page),
                'end_page_id': str(end_page)
            }

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Processing...", total=None)

                response = requests.post(url, files=files, data=data, timeout=600)

                progress.update(task, completed=True)

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
        return None


async def process_websocket_stream(pdf_path, server_url, lang, include_discarded, start_page=0, end_page=99999):
    """Process PDF using WebSocket streaming API."""
    console.print(Panel.fit(
        "[bold magenta]WebSocket Streaming Mode[/bold magenta]",
        border_style="magenta"
    ))

    if not os.path.exists(pdf_path):
        console.print(f"[red]Error:[/red] File not found: {pdf_path}")
        return None

    # Convert http to ws URL
    ws_url = server_url.replace('http://', 'ws://').replace('https://', 'wss://')
    ws_url = f"{ws_url}/layout_ocr/stream"

    console.print(f"[magenta]→[/magenta] Connecting to: {ws_url}")
    console.print(f"[magenta]→[/magenta] PDF: {pdf_path}")
    console.print(f"[magenta]→[/magenta] Language: {lang}")
    if end_page < 99999:
        console.print(f"[magenta]→[/magenta] Page range: {start_page} - {end_page}")

    start_time = time.time()
    all_pages = []
    total_pages = None

    try:
        # Read and encode PDF
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
            pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')

        console.print(f"[magenta]→[/magenta] PDF size: {len(pdf_bytes) / 1024:.1f} KB")

        async with websockets.connect(ws_url, max_size=100*1024*1024) as websocket:
            # Send request
            request = {
                "pdf_base64": pdf_b64,
                "filename": Path(pdf_path).name,
                "lang": lang,
                "parse_method": "auto",
                "include_discarded": include_discarded,
                "start_page_id": start_page,
                "end_page_id": end_page
            }

            console.print("[magenta]→[/magenta] Sending PDF...")
            await websocket.send(json.dumps(request))

            # Receive streaming results
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = None

                while True:
                    message = await websocket.recv()
                    msg = json.loads(message)
                    status = msg.get('status')

                    if status == 'started':
                        console.print(f"[green]✓[/green] {msg.get('message', 'Started')}")

                    elif status == 'analyzing':
                        total_pages = msg.get('total_pages', 0)
                        console.print(f"[cyan]→[/cyan] Total pages: {total_pages}")
                        task = progress.add_task(
                            f"[cyan]Processing {total_pages} pages...",
                            total=total_pages
                        )

                    elif status == 'processing':
                        page_idx = msg.get('page_index', 0)
                        page_progress = msg.get('progress', 0)
                        page_data = msg.get('data', {})

                        all_pages.append(page_data)

                        if task is not None:
                            progress.update(
                                task,
                                completed=page_idx + 1,
                                description=f"[cyan]Page {page_idx + 1}/{total_pages} ({page_progress*100:.0f}%)"
                            )

                        # Print page summary
                        console.print(f"\n[bold yellow]Page {page_idx + 1} completed:[/bold yellow]")
                        print_page_summary(page_data)
                        console.print()

                    elif status == 'completed':
                        elapsed = time.time() - start_time
                        console.print(f"\n[green]✓[/green] All pages completed in {elapsed:.1f}s")
                        console.print(f"[green]✓[/green] {msg.get('message', 'Done')}")
                        break

                    elif status == 'page_error':
                        page_idx = msg.get('page_index', 'N/A')
                        error_msg = msg.get('message', 'Unknown error')
                        console.print(f"[yellow]⚠[/yellow] Page {page_idx} error: {error_msg}")

                    elif status == 'error':
                        error_msg = msg.get('message', 'Unknown error')
                        console.print(f"[red]Error:[/red] {error_msg}")
                        return None

        # Construct result
        result = {
            "status": "success",
            "mode": "websocket_streaming",
            "backend": "pipeline",
            "processing_time": elapsed,
            "files": [{
                "filename": Path(pdf_path).name,
                "pages": all_pages
            }]
        }

        return result

    except websockets.exceptions.WebSocketException as e:
        console.print(f"[red]WebSocket Error:[/red] {e}")
        return None
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description='Layout OCR API Client',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # HTTP batch processing
  python layout_ocr_client.py document.pdf --mode http --lang ko

  # WebSocket streaming
  python layout_ocr_client.py document.pdf --mode websocket --lang ko

  # Custom server
  python layout_ocr_client.py document.pdf --mode websocket --server http://192.168.1.100:8000

  # Include discarded blocks (headers/footers)
  python layout_ocr_client.py document.pdf --mode http --include-discarded

  # Process specific page range (pages 0-9)
  python layout_ocr_client.py document.pdf --mode http --start-page 0 --end-page 9
        """
    )

    parser.add_argument(
        'pdf_path',
        help='Path to PDF file'
    )
    parser.add_argument(
        '--mode',
        choices=['http', 'websocket'],
        default='http',
        help='Processing mode (default: http)'
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
        '--start-page',
        type=int,
        default=0,
        help='Start page index (default: 0)'
    )
    parser.add_argument(
        '--end-page',
        type=int,
        default=99999,
        help='End page index (default: 99999, process all pages)'
    )
    parser.add_argument(
        '--output',
        help='Output JSON file path (default: <pdf_name>_result.json)'
    )

    args = parser.parse_args()

    # Validate PDF file
    if not os.path.exists(args.pdf_path):
        console.print(f"[red]Error:[/red] File not found: {args.pdf_path}")
        sys.exit(1)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        pdf_name = Path(args.pdf_path).stem
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = f"{pdf_name}_{args.mode}_{timestamp}.json"

    console.print(f"\n[bold]Layout OCR Client[/bold]")
    console.print(f"Mode: [{'cyan' if args.mode == 'http' else 'magenta'}]{args.mode.upper()}[/]")
    console.print()

    # Process based on mode
    if args.mode == 'http':
        result = process_http_batch(
            args.pdf_path,
            args.server,
            args.lang,
            args.include_discarded,
            args.start_page,
            args.end_page
        )
    else:  # websocket
        result = asyncio.run(process_websocket_stream(
            args.pdf_path,
            args.server,
            args.lang,
            args.include_discarded,
            args.start_page,
            args.end_page
        ))

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
            if 'processing_time' in result:
                stats_table.add_row("Processing Time", f"{result['processing_time']:.1f}s")

            console.print(stats_table)

        console.print(f"\n[green]✓[/green] All done!")
    else:
        console.print(f"\n[red]✗[/red] Processing failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
