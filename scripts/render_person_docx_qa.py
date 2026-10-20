"""Run the document skill's renderer with local PDFium when Poppler is absent.

The skill renderer owns DOCX -> PDF conversion. PDFium only rasterizes the
resulting physical PDF pages; it does not approximate Word layout from HTML.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('docx', type=Path)
    parser.add_argument('--renderer', type=Path, required=True)
    parser.add_argument('--soffice-directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dpi', type=int, default=110)
    args = parser.parse_args()
    import pypdfium2 as pdfium
    os.environ['PATH'] = str(args.soffice_directory.resolve()) + os.pathsep + os.environ.get('PATH', '')
    spec = importlib.util.spec_from_file_location('document_skill_renderer', args.renderer)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)

    def rasterize_pdf(path, *, dpi, output_folder, **kwargs):
        document = pdfium.PdfDocument(path)
        paths = []
        try:
            for index in range(len(document)):
                page = document[index]
                bitmap = page.render(scale=dpi/72)
                try:
                    output = Path(output_folder) / f'page0001-{index+1}.png'
                    bitmap.to_pil().save(output)
                    paths.append(str(output))
                finally:
                    bitmap.close(); page.close()
        finally:
            document.close()
        return paths

    renderer.convert_from_path = rasterize_pdf
    args.output.mkdir(parents=True, exist_ok=True)
    paths = renderer.rasterize(str(args.docx.resolve()), str(args.output.resolve()), args.dpi, True, True)
    (args.output / 'render-receipt.json').write_text(json.dumps({'source': str(args.docx.resolve()),
        'skill_renderer': str(args.renderer), 'pdf_rasterizer': 'PDFium', 'dpi': args.dpi, 'page_count': len(paths),
        'pages': paths, 'visual_review_status': 'not_yet_reviewed'}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'page_count': len(paths), 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
