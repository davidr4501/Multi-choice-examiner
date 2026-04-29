import re
import os
import uuid
import fitz  # PyMuPDF
from flask import current_app

# ---------------------------------------------------------------------------
# Question-number patterns (tried in order; best-scoring result is kept)
# ---------------------------------------------------------------------------
# Format A: "1." / "1)" / "1:" followed by whitespace, with optional "Q"/"Q." prefix
_Q_PATTERN_SEP = re.compile(
    r'(?:^|\n)[ \t]*(?:[Qq]\.?\s*)?(\d{1,3})[.):][ \t]+(.+?)'
    r'(?=\n[ \t]*(?:[Qq]\.?\s*)?\d{1,3}[.):][ \t]|\Z)',
    re.DOTALL | re.MULTILINE,
)

# Format B: "1  " (number followed by 2+ spaces – Cambridge / IB style)
_Q_PATTERN_SPACE = re.compile(
    r'(?:^|\n)[ \t]*(\d{1,3})[ \t]{2,}(.+?)'
    r'(?=\n[ \t]*\d{1,3}[ \t]{2,}|\Z)',
    re.DOTALL | re.MULTILINE,
)

# Format C: combined – either separator or 2+ spaces
_Q_PATTERN_COMBINED = re.compile(
    r'(?:^|\n)[ \t]*(?:[Qq]\.?\s*)?(\d{1,3})(?:[.):][ \t]+|[ \t]{2,})(.+?)'
    r'(?=\n[ \t]*(?:[Qq]\.?\s*)?\d{1,3}(?:[.):][ \t]|[ \t]{2,})|\Z)',
    re.DOTALL | re.MULTILINE,
)

_Q_PATTERNS = [_Q_PATTERN_SEP, _Q_PATTERN_SPACE, _Q_PATTERN_COMBINED]

# ---------------------------------------------------------------------------
# Option pattern – handles A) A. (A) A   (2+ spaces) in one expression
# Groups: (1) letter from "(A)" form  (2) letter from "A)" / "A  " form  (3) option text
# ---------------------------------------------------------------------------
_OPT_PATTERN = re.compile(
    r'(?:^|\n)[ \t]*(?:\(([A-D])\)|([A-D])(?:[.):,][ \t]*|[ \t]{2,}))(.+?)'
    r'(?=\n[ \t]*(?:\([A-D]\)|[A-D](?:[.):,][ \t]|[ \t]{2,}))|\Z)',
    re.DOTALL | re.MULTILINE,
)


def _score_questions(questions):
    """Score a candidate parse – prefer more questions each with 4 options."""
    score = 0
    for q in questions:
        score += 1
        for key in ('option_a', 'option_b', 'option_c', 'option_d'):
            if q.get(key):
                score += 2
    return score


def _extract_page_text(page):
    """
    Extract text from a PDF page in correct reading order.

    For two-column layouts the default get_text() output can interleave
    columns.  We sort text blocks so that the left column always comes first.
    """
    page_width = page.rect.width
    blocks = page.get_text('blocks')          # [(x0,y0,x1,y1,text,block_no,type),...]
    text_blocks = [b for b in blocks if b[6] == 0]  # type 0 = text

    if not text_blocks:
        return ''

    mid = page_width / 2
    left_blocks = [b for b in text_blocks if b[0] < mid]
    right_blocks = [b for b in text_blocks if b[0] >= mid]

    # Only use column-aware ordering when there are blocks in both halves
    if left_blocks and right_blocks:
        left_blocks.sort(key=lambda b: b[1])
        right_blocks.sort(key=lambda b: b[1])
        sorted_blocks = left_blocks + right_blocks
    else:
        sorted_blocks = sorted(text_blocks, key=lambda b: (b[1], b[0]))

    return '\n'.join(b[4].strip() for b in sorted_blocks if b[4].strip())


def parse_exam_pdf(pdf_path, images_folder):
    """
    Parse an exam PDF and extract MCQ questions with options and images.
    Returns a list of dicts with question data.

    Handles common question formats:
      • "1."  "1)"  "1:"  (with optional "Q" / "Q." prefix)
      • "1  " (number + 2+ spaces – Cambridge / IB style)
    And option formats:
      • "A)"  "A."  "(A)"  "A  " (Cambridge style)
    """
    questions = []

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        current_app.logger.error(f'Failed to open PDF: {e}')
        return questions

    full_text = ''
    page_images = {}

    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = _extract_page_text(page)
        full_text += page_text + '\n'

        image_list = page.get_images(full=True)
        page_img_paths = []
        for img in image_list:
            try:
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image['image']

                img_filename = f'q_{uuid.uuid4().hex}.png'
                img_path = os.path.join(images_folder, img_filename)

                from PIL import Image
                import io
                img_obj = Image.open(io.BytesIO(image_bytes))
                img_obj.save(img_path, 'PNG')
                page_img_paths.append(os.path.join('uploads', 'images', img_filename))
            except Exception as e:
                current_app.logger.warning(f'Failed to extract image: {e}')

        page_images[page_num] = page_img_paths

    doc.close()

    if not full_text.strip():
        current_app.logger.warning(
            'No text extracted from PDF – it may be a scanned/image-only PDF. '
            'Consider using a text-based or OCR-processed PDF.'
        )
        return []

    current_app.logger.debug(
        f'PDF text extracted ({len(full_text)} chars). '
        f'First 500 chars: {full_text[:500]!r}'
    )

    questions = _parse_questions_from_text(full_text, page_images)

    if not questions:
        current_app.logger.warning(
            f'No questions matched after parsing. '
            f'First 1000 chars of extracted text: {full_text[:1000]!r}'
        )

    return questions


def _parse_with_q_pattern(text, q_pattern, page_images):
    """Apply one question pattern + the universal option pattern and return results."""
    matches = list(q_pattern.finditer(text))
    questions = []

    for i, match in enumerate(matches):
        q_num = int(match.group(1))
        q_block = match.group(0).strip()

        options = {}
        opt_matches = list(_OPT_PATTERN.finditer(q_block))

        for om in opt_matches:
            letter = om.group(1) or om.group(2)
            if not letter:
                continue
            opt_text = om.group(3).strip().split('\n')[0].strip()
            options[letter.upper()] = opt_text

        if opt_matches:
            q_text = q_block[:opt_matches[0].start()].strip()
        else:
            q_text = q_block

        # Strip leading question-number prefix
        q_text = re.sub(
            r'^[ \t]*(?:[Qq]\.?\s*)?\d{1,3}(?:[.):][ \t]+|[ \t]+)', '', q_text
        ).strip()

        # Associate images proportionally across questions
        has_image = False
        image_path = None
        if page_images:
            pages = sorted(page_images.keys())
            # len(matches) >= 1 guaranteed here (we're inside the loop)
            q_fraction = i / len(matches) if len(matches) > 1 else 0
            estimated_page_idx = min(int(q_fraction * len(pages)), len(pages) - 1)
            page_key = pages[estimated_page_idx]
            imgs = page_images.get(page_key, [])
            if imgs:
                img_idx = i % len(imgs)
                has_image = True
                image_path = imgs[img_idx]

        if q_text or options:
            questions.append({
                'question_number': q_num,
                'question_text': q_text,
                'option_a': options.get('A', ''),
                'option_b': options.get('B', ''),
                'option_c': options.get('C', ''),
                'option_d': options.get('D', ''),
                'has_image': has_image,
                'image_path': image_path,
            })

    questions.sort(key=lambda x: x['question_number'])
    return questions


def _parse_questions_from_text(text, page_images):
    """
    Try every question-number pattern and return the parse that scores highest
    (most questions × options found).
    """
    best = []
    for i, q_pattern in enumerate(_Q_PATTERNS):
        try:
            result = _parse_with_q_pattern(text, q_pattern, page_images)
            if _score_questions(result) > _score_questions(best):
                best = result
        except Exception as exc:
            current_app.logger.warning(f'Pattern {i} failed: {exc}')

    return best


def parse_markscheme_pdf(pdf_path):
    """
    Parse a mark scheme PDF and return a dict mapping question_number -> correct_answer.
    """
    answers = {}

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        current_app.logger.error(f'Failed to open mark scheme PDF: {e}')
        return answers

    full_text = ''
    for page_num in range(len(doc)):
        full_text += doc[page_num].get_text()
    doc.close()

    patterns = [
        re.compile(r'(\d{1,3})\s*[.):\s]\s*([A-Da-d])\b'),
        re.compile(r'[Qq](?:uestion\s*)?(\d{1,3})\s*[.):]\s*([A-Da-d])\b'),
    ]

    for pattern in patterns:
        for match in pattern.finditer(full_text):
            q_num = int(match.group(1))
            answer = match.group(2).upper()
            if answer in ('A', 'B', 'C', 'D') and q_num not in answers:
                answers[q_num] = answer

    return answers
