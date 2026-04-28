import re
import os
import uuid
import fitz  # PyMuPDF
from flask import current_app


def parse_exam_pdf(pdf_path, images_folder):
    """
    Parse an exam PDF and extract MCQ questions with options and images.
    Returns a list of dicts with question data.
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
        full_text += f'\n[PAGE_{page_num}]\n'
        full_text += page.get_text()

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

    questions = _parse_questions_from_text(full_text, page_images)
    return questions


def _parse_questions_from_text(text, page_images):
    """Parse questions from extracted text."""
    clean_lines = []
    current_page = 0

    for line in text.split('\n'):
        page_match = re.match(r'\[PAGE_(\d+)\]', line)
        if page_match:
            current_page = int(page_match.group(1))
        else:
            clean_lines.append(line)

    clean_text = '\n'.join(clean_lines)

    # Find question blocks: number + period/paren followed by text
    question_pattern = re.compile(
        r'(?:^|\n)\s*(?:Q\.?\s*)?(\d{1,3})[.)]\s+(.+?)(?=(?:\n\s*(?:Q\.?\s*)?\d{1,3}[.)]\s+)|\Z)',
        re.DOTALL | re.MULTILINE,
    )

    option_pattern = re.compile(
        r'(?:^|\n)\s*([A-D])[.)]\s+(.+?)(?=(?:\n\s*[A-D][.)]\s+)|\n\s*(?:Q\.?\s*)?\d{1,3}[.)]\s+|\Z)',
        re.DOTALL | re.MULTILINE,
    )

    matches = list(question_pattern.finditer(clean_text))
    questions = []

    for i, match in enumerate(matches):
        q_num = int(match.group(1))
        q_block = match.group(0).strip()

        options = {}
        opt_matches = list(option_pattern.finditer(q_block))

        for opt_match in opt_matches:
            letter = opt_match.group(1).upper()
            opt_text = opt_match.group(2).strip()
            opt_text = re.split(r'\n\s*[A-D][.)]\s+', opt_text)[0].strip()
            options[letter] = opt_text

        q_text = q_block
        if opt_matches:
            first_opt_start = opt_matches[0].start()
            q_text = q_block[:first_opt_start].strip()
            q_text = re.sub(r'^\s*(?:Q\.?\s*)?\d{1,3}[.)]\s+', '', q_text).strip()
        else:
            q_text = re.sub(r'^\s*(?:Q\.?\s*)?\d{1,3}[.)]\s+', '', q_text).strip()

        # Associate images proportionally across questions
        has_image = False
        image_path = None
        if page_images:
            pages = sorted(page_images.keys())
            if matches:
                q_fraction = i / len(matches)
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
