#!/usr/bin/env python3
"""Extract ```mermaid fenced blocks from Markdown files and emit a single
self-contained HTML page that renders them with mermaid.js.

mermaid.min.js vendored next to this script (tools/mermaid.min.js) is inlined into
the HTML, so the output is fully offline — no network at render time. If the vendored
copy is missing, it falls back to loading mermaid from the jsdelivr CDN.

Then print to PDF with headless Chrome, e.g.:

  python3 tools/mermaid_to_html.py COMBAT_FLOW.md -o build_docs/combat_flow.html
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
      --headless=new --disable-gpu --no-pdf-header-footer \
      --virtual-time-budget=15000 \
      --print-to-pdf=build_docs/combat_flow.pdf \
      build_docs/combat_flow.html
"""
import argparse
import html
import re
from pathlib import Path

MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
# Capture the nearest preceding Markdown heading as each diagram's caption.
HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)


def extract(md_text: str):
    """Yield (caption, mermaid_source) for each fenced mermaid block."""
    for m in MERMAID_BLOCK.finditer(md_text):
        preceding = md_text[: m.start()]
        headings = HEADING.findall(preceding)
        caption = headings[-1].strip() if headings else ""
        yield caption, m.group(1).strip()


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
{mermaid_js}
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; margin: 24px; color: #1a1a1a; }}
  h1.doc-title {{ font-size: 22px; border-bottom: 2px solid #444; padding-bottom: 6px; }}
  .diagram {{ page-break-inside: avoid; break-inside: avoid; margin: 18px 0 34px; }}
  .diagram h2 {{ font-size: 15px; color: #333; margin: 0 0 8px; }}
  .mermaid {{ background: #fafafa; border: 1px solid #e2e2e2; border-radius: 6px; padding: 14px; }}
  /* One diagram per printed page keeps large flowcharts readable. */
  .diagram + .diagram {{ page-break-before: always; }}
</style>
</head>
<body>
<h1 class="doc-title">{title}</h1>
{body}
<script>
  mermaid.initialize({{ startOnLoad: true, theme: "default", securityLevel: "loose",
                        flowchart: {{ useMaxWidth: true }} }});
</script>
</body>
</html>
"""


def mermaid_script_tag():
    """Inline the vendored mermaid.min.js (offline); else fall back to the CDN."""
    vendored = Path(__file__).resolve().parent / "mermaid.min.js"
    if vendored.is_file():
        js = vendored.read_text(encoding="utf-8")
        # Guard against a literal </script> inside the bundle closing the tag early.
        js = js.replace("</script", "<\\/script")
        return f"<script>\n{js}\n</script>"
    return '<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>'


def build_html(md_paths):
    title = ", ".join(p.name for p in md_paths)
    sections = []
    for p in md_paths:
        text = p.read_text(encoding="utf-8")
        for caption, src in extract(text):
            cap_html = f"<h2>{html.escape(caption)}</h2>" if caption else ""
            sections.append(
                f'<div class="diagram">{cap_html}<pre class="mermaid">\n{html.escape(src)}\n</pre></div>'
            )
    if not sections:
        raise SystemExit("No ```mermaid blocks found in: " + title)
    return PAGE.format(title=html.escape(title), body="\n".join(sections),
                       mermaid_js=mermaid_script_tag())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("markdown", nargs="+", type=Path, help="Markdown file(s) with mermaid blocks")
    ap.add_argument("-o", "--out", type=Path, required=True, help="Output HTML path")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build_html(args.markdown), encoding="utf-8")
    n = sum(len(list(extract(p.read_text(encoding="utf-8")))) for p in args.markdown)
    print(f"Wrote {args.out} ({n} diagram(s)).")


if __name__ == "__main__":
    main()
