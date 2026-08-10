"""Vision-OCR model dialects: per-model request recipe + response parser.

Vision OCR models served over OpenAI-compatible endpoints differ in exactly
two ways: how the request is shaped (prompt, sampling, vLLM extras, whether
the image precedes the text part) and what dialect the response speaks
(Unlimited-OCR's ``text [x1, y1, x2, y2]…`` layout lines, chandra's
``<div data-bbox data-label>`` structured HTML, or plain text). Everything
else — page rendering, concurrency, the blank-page ink check, the fail-closed
guarantee — is shared and lives in ``vision_llm_ocr``; it must not vary per
model.

A dialect only supplies *defaults*: an explicitly configured
``VISION_OCR_PROMPT`` / ``VISION_OCR_FALLBACK_PROMPT`` / ``VISION_OCR_MAX_TOKENS``
/ ``VISION_OCR_EXTRA_BODY`` always wins.

Mirrors the detector registry (`build_detectors`): an unknown dialect name is
refused loudly, never parsed with a guessed fallback — a parser that silently
mis-reads a response would drop text, and dropped text here means undetected
PII.

Bounding boxes are 0–1000 page-normalized with a top-left origin (the
`LayoutLine` convention) for every dialect that emits them; chandra's
``data-bbox`` values were verified to be resolution-independent in this space.
"""

import re
from html.parser import HTMLParser


class TranscribedLine:
    """One output line: text plus optional normalized bounding box."""

    def __init__(self, text: str, box: tuple[int, int, int, int] | None = None):
        self.text = text
        self.box = box


class OcrDialect:
    """Request recipe and response parser for one vision OCR model family."""

    name: str
    default_prompt: str
    default_fallback_prompt: str  # "" = no fallback retry for this dialect
    default_extra_body: dict
    default_max_tokens: int
    #: Whether the image part precedes the text part in the user message.
    image_first: bool = False
    #: Sampling override the model's recipe calls for; None = endpoint default.
    top_p: float | None = None

    def parse(self, raw: str) -> list[TranscribedLine]:
        raise NotImplementedError


# --- unlimited_ocr -----------------------------------------------------------

# Model markup such as <|ref|>…<|/ref|> emitted with skip_special_tokens=false.
_SPECIAL_TOKENS = re.compile(r"<\|[^|>]{0,40}\|>")
# Unlimited-OCR line prefixes: element type + bounding box, e.g.
# "text [112, 76, 681, 95]Patientin: …". The boxes drive the
# layout-preserving redacted-PDF reconstruction; the prefix itself is
# stripped from the text output.
_LAYOUT_LINE = re.compile(
    r"^([a-z_]{1,20}) \[(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\](.*)$", re.IGNORECASE
)


class UnlimitedOcrDialect(OcrDialect):
    """baidu/Unlimited-OCR served by vLLM (the recipe in .env.example)."""

    name = "unlimited_ocr"
    default_prompt = "<image>document parsing."
    # The layout parser occasionally classifies a whole page as a single image
    # (dense barcodes, handwriting, redaction bars) and emits no text; the
    # flat "Free OCR." mode transcribes it.
    default_fallback_prompt = "<image>Free OCR."
    default_extra_body = {
        "skip_special_tokens": False,
        "vllm_xargs": {"ngram_size": 35, "window_size": 128},
    }
    default_max_tokens = 8192

    def parse(self, raw: str) -> list[TranscribedLine]:
        cleaned = _SPECIAL_TOKENS.sub("", raw).strip()
        lines: list[TranscribedLine] = []
        for line in cleaned.splitlines():
            match = _LAYOUT_LINE.match(line)
            if match:
                box = tuple(int(match.group(i)) for i in range(2, 6))
                lines.append(TranscribedLine(text=match.group(6), box=box))  # type: ignore[arg-type]
            elif line.strip():
                lines.append(TranscribedLine(text=line))
        return lines


# --- chandra -----------------------------------------------------------------

_CODE_FENCE = re.compile(r"^```[a-z]*\n(.*)\n```$", re.DOTALL)
#: Tags that end the current output line when they open and/or close.
_LINE_BREAK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table", "ul", "ol"}


class _ChandraHTMLParser(HTMLParser):
    """chandra structured HTML -> transcribed lines.

    Blocks are ``<div data-label="…" data-bbox="x1 y1 x2 y2">``; chandra boxes
    whole blocks, not lines, so a multi-line block's box is subdivided
    vertically into equal per-line strips. That is an approximation, but it is
    what the reconstructed redacted PDF needs: text placement and redaction
    boxes both come from these strips, so they stay consistent with each
    other. Text outside any block (e.g. a plain-text fallback response)
    becomes unboxed lines, so the parser also accepts non-HTML output rather
    than dropping it.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[TranscribedLine] = []
        self._box: tuple[int, int, int, int] | None = None
        self._in_block = False
        self._div_depth = 0
        self._block_start = 0  # index of the open block's first line
        self._buffer: list[str] = []
        self._list_stack: list[int] = []  # item counter per level; -1 = unordered

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._buffer = []
        if text:
            self.lines.append(TranscribedLine(text=text, box=self._box))

    def _close_block(self) -> None:
        """Split the block box into equal vertical strips, one per line."""
        block_lines = self.lines[self._block_start :]
        if self._box is None or len(block_lines) < 2:
            return
        x1, y1, x2, y2 = self._box
        height = y2 - y1
        count = len(block_lines)
        for index, line in enumerate(block_lines):
            line.box = (
                x1,
                y1 + round(index * height / count),
                x2,
                y1 + round((index + 1) * height / count),
            )

    @staticmethod
    def _parse_box(value: str | None) -> tuple[int, int, int, int] | None:
        numbers = re.findall(r"-?\d+", value or "")
        if len(numbers) != 4:
            return None
        x1, y1, x2, y2 = (min(max(int(n), 0), 1000) for n in numbers)
        return (x1, y1, x2, y2)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "div":
            if self._in_block:
                self._div_depth += 1
            elif "data-label" in attributes:
                self._flush()
                self._in_block = True
                self._div_depth = 1
                self._box = self._parse_box(attributes.get("data-bbox"))
                self._block_start = len(self.lines)
            return
        if tag == "br" or tag in _LINE_BREAK_TAGS:
            self._flush()
        match tag:
            case "ul":
                self._list_stack.append(-1)
            case "ol":
                self._list_stack.append(0)
            case "li":
                if self._list_stack and self._list_stack[-1] >= 0:
                    self._list_stack[-1] += 1
                    self._buffer.append(f"{self._list_stack[-1]}. ")
                else:
                    self._buffer.append("- ")
            case "td" | "th":
                if "".join(self._buffer).strip():
                    self._buffer.append(" | ")
            case "img":
                # chandra describes figures and physically redacted regions via
                # alt text ("Redacted patient name") instead of hallucinating
                # content — keep that as a visible line of the reconstruction.
                self._flush()
                if attributes.get("alt"):
                    self._buffer.append(f"[{attributes['alt']}]")
                    self._flush()

    def handle_endtag(self, tag):
        if tag == "div":
            if self._in_block:
                self._div_depth -= 1
                if self._div_depth == 0:
                    self._flush()
                    self._close_block()
                    self._in_block = False
                    self._box = None
            return
        if tag in _LINE_BREAK_TAGS:
            self._flush()
        if tag in ("ul", "ol") and self._list_stack:
            self._list_stack.pop()

    def handle_data(self, data):
        if self._in_block:
            # Inside HTML, newlines are formatting noise (HTML semantics);
            # real line breaks arrive as <br/> or element boundaries.
            self._buffer.append(data)
            return
        for index, part in enumerate(data.split("\n")):
            if index:
                self._flush()
            self._buffer.append(part)


class ChandraDialect(OcrDialect):
    """datalab chandra (e.g. chandra-ocr-2) served by vLLM: structured HTML
    blocks with 0–1000-normalized ``data-bbox`` coordinates."""

    name = "chandra"
    default_prompt = (
        "OCR this image into structured HTML. Preserve reading order, headings, "
        "paragraphs, lists, tables, math, code, and document layout. Use semantic "
        "HTML and keep complex tables as HTML. Return only the OCR result."
    )
    default_fallback_prompt = (
        "Transcribe every piece of visible text in this image in reading order. "
        "Return only the transcribed text."
    )
    default_extra_body: dict = {}
    default_max_tokens = 12384
    image_first = True
    top_p = 0.1

    def parse(self, raw: str) -> list[TranscribedLine]:
        stripped = raw.strip()
        fenced = _CODE_FENCE.match(stripped)
        if fenced:
            stripped = fenced.group(1)
        parser = _ChandraHTMLParser()
        parser.feed(stripped)
        parser.close()
        parser._flush()
        return parser.lines


# --- plain -------------------------------------------------------------------


class PlainDialect(OcrDialect):
    """Any generic vision model that returns the transcription as plain text
    or Markdown. No layout boxes, so scanned-PDF export falls back to the
    rasterized full-page reconstruction."""

    name = "plain"
    default_prompt = (
        "Transcribe all text in this image in reading order, preserving the "
        "layout as plain text. Return only the transcription."
    )
    default_fallback_prompt = ""
    default_extra_body: dict = {}
    default_max_tokens = 8192

    def parse(self, raw: str) -> list[TranscribedLine]:
        return [TranscribedLine(text=line.strip()) for line in raw.splitlines() if line.strip()]


DIALECTS: dict[str, type[OcrDialect]] = {
    dialect.name: dialect for dialect in (UnlimitedOcrDialect, ChandraDialect, PlainDialect)
}


def build_dialect(name: str) -> OcrDialect:
    """Instantiate a dialect by name; unknown names are refused loudly."""
    dialect = DIALECTS.get(name.strip())
    if dialect is None:
        known = ", ".join(sorted(DIALECTS))
        raise ValueError(
            f"Unknown vision OCR dialect '{name}' (VISION_OCR_DIALECT); known: {known}."
        )
    return dialect()
