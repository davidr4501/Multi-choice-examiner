import os
import base64
import uuid
import json
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io
from flask import current_app

def configure_gemini():
    """Configures the Gemini API key."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        current_app.logger.error("GEMINI_API_KEY environment variable not set.")
        raise ValueError("GEMINI_API_KEY environment variable not set.")
    genai.configure(api_key=api_key)

def save_image_from_base64(base64_str, images_folder):
    """Saves a base64 encoded image to the images folder."""
    try:
        missing_padding = len(base64_str) % 4
        if missing_padding:
            base64_str += '=' * (4 - missing_padding)
        img_data = base64.b64decode(base64_str)
        img_filename = f'img_{uuid.uuid4().hex}.png'
        img_path = os.path.join(images_folder, img_filename)
        with open(img_path, 'wb') as f:
            f.write(img_data)
        return os.path.join('uploads', 'images', img_filename)
    except Exception as e:
        current_app.logger.error(f"Could not save image from base64: {e}")
        return None

def handle_gemini_response(response):
    """Checks for safety blocks and returns a status and the extracted text."""
    if not response.candidates:
        return 'BLOCKED', "Response was blocked by safety filters."
    
    candidate = response.candidates[0]
    # STOP = 1, MAX_TOKENS = 2, RECITATION = 4
    if candidate.finish_reason not in [1, 2]:
        msg = f"Response stopped for reason code: {candidate.finish_reason}"
        if candidate.finish_reason == 4:
            msg = "Response blocked for recitation from copyrighted material."
        current_app.logger.error(msg)
        return 'ERROR', msg
        
    if not hasattr(candidate, 'content') or not candidate.content.parts:
        if hasattr(candidate, 'safety_ratings'):
             current_app.logger.error(f"Safety ratings: {candidate.safety_ratings}")
        return 'BLOCKED', "Response blocked: No content parts returned."

    return 'SUCCESS', response.text

def parse_exam_with_gemini(pdf_path, images_folder):
    """Parses an exam PDF, returning a dict with status and data."""
    try:
        configure_gemini()
        # Set a higher token limit
        generation_config = genai.GenerationConfig(max_output_tokens=8192)
        model = genai.GenerativeModel('models/gemini-2.5-flash-image', generation_config=generation_config)
        doc = fitz.open(pdf_path)
        pdf_images = [Image.open(io.BytesIO(page.get_pixmap().tobytes("png"))) for page in doc]
        doc.close()
    except Exception as e:
        return {'status': 'ERROR', 'message': f"Setup error: {e}", 'data': []}

    prompt = """
    From the document images, extract all multiple-choice questions. For each question, provide a JSON object with the following fields:
    - `question_number`: The question number.
    - `question_html`: The full question as an HTML string. Any images in the question should be represented by an `<img>` tag with a placeholder like `[IMAGE_0]`.
    - `options`: A dictionary with keys "A", "B", "C", "D" and HTML string values. Image placeholders can also be used here.
    - `images`: A list of the actual image data that corresponds to the placeholders.
    - `answers_embedded`: A boolean, `true` if the A, B, C, D labels are part of an image or table in the question itself.
    - `correct_answer`: The correct letter, if available.

    Return a single JSON list of these objects.
    """

    try:
        current_app.logger.info(f"--- Gemini Prompt (Exam) ---\n{prompt}\n--------------------")
        response = model.generate_content([prompt] + pdf_images)
        status, response_text = handle_gemini_response(response)
        
        if status != 'SUCCESS':
            return {'status': status, 'message': response_text, 'data': []}

        current_app.logger.info(f"--- Raw Gemini Response (Exam) ---\n{response_text}\n--------------------")

        if not response_text or not response_text.strip():
            return {'status': 'ERROR', 'message': 'Gemini returned an empty response.', 'data': []}

        cleaned_response = response_text.strip().replace('```json', '').replace('```', '')
        parsed_questions = json.loads(cleaned_response)
        
        formatted_questions = []
        for q_data in parsed_questions:
            question_html = q_data.get('question_html', '')
            options = q_data.get('options', {})
            
            images_base64 = q_data.get('images', [])
            for i, img_base64 in enumerate(images_base64):
                img_path_relative_to_static = save_image_from_base64(img_base64, images_folder)
                if img_path_relative_to_static:
                    placeholder = f'[IMAGE_{i}]'
                    full_image_url = f'/static/{img_path_relative_to_static}'
                    question_html = question_html.replace(placeholder, full_image_url)
                    for key, val in options.items():
                        if isinstance(val, str):
                            options[key] = val.replace(placeholder, full_image_url)

            formatted_q = {
                'question_number': q_data.get('question_number'),
                'question_html': question_html,
                'option_a': options.get('A', ''),
                'option_b': options.get('B', ''),
                'option_c': options.get('C', ''),
                'option_d': options.get('D', ''),
                'answers_embedded': q_data.get('answers_embedded', False),
                'correct_answer': q_data.get('correct_answer'),
            }
            formatted_questions.append(formatted_q)
            
        return {'status': 'SUCCESS', 'message': f'{len(formatted_questions)} questions found.', 'data': formatted_questions}

    except json.JSONDecodeError as e:
        current_app.logger.error(f"Failed to decode JSON. Error: {e}. Response was: {response_text}")
        return {'status': 'ERROR', 'message': 'Gemini returned a non-JSON response.', 'data': []}
    except Exception as e:
        return {'status': 'ERROR', 'message': f"An unexpected error occurred: {e}", 'data': []}

def parse_markscheme_with_gemini(pdf_path):
    """Parses a mark scheme PDF, returning a dict with status and data."""
    try:
        configure_gemini()
        generation_config = genai.GenerationConfig(max_output_tokens=8192)
        model = genai.GenerativeModel('models/gemini-2.5-flash-image', generation_config=generation_config)
        doc = fitz.open(pdf_path)
        images = [Image.open(io.BytesIO(page.get_pixmap().tobytes("png"))) for page in doc]
        doc.close()
    except Exception as e:
        return {'status': 'ERROR', 'message': f"Setup error: {e}", 'data': {}}

    prompt = """
    From the document images, extract the question number and the correct answer letter for each question.
    Return a single JSON object where the keys are the question numbers (as strings) and the values are the correct answer letters.
    """

    try:
        current_app.logger.info(f"--- Gemini Prompt (Markscheme) ---\n{prompt}\n--------------------")
        response = model.generate_content([prompt] + images)
        status, response_text = handle_gemini_response(response)

        if status != 'SUCCESS':
            return {'status': status, 'message': response_text, 'data': {}}

        current_app.logger.info(f"--- Raw Gemini Response (Markscheme) ---\n{response_text}\n--------------------")

        if not response_text or not response_text.strip():
            return {'status': 'ERROR', 'message': 'Gemini returned an empty response for markscheme.', 'data': {}}

        cleaned_response = response_text.strip().replace('```json', '').replace('```', '')
        correct_answers = json.loads(cleaned_response)
        data = {int(k): v for k, v in correct_answers.items()}
        return {'status': 'SUCCESS', 'message': f'{len(data)} answers found.', 'data': data}
        
    except json.JSONDecodeError as e:
        current_app.logger.error(f"Failed to decode markscheme JSON. Error: {e}. Response was: {response_text}")
        return {'status': 'ERROR', 'message': 'Gemini returned a non-JSON response for the markscheme.', 'data': {}}
    except Exception as e:
        return {'status': 'ERROR', 'message': f"An unexpected error occurred: {e}", 'data': {}}
