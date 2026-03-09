import io
from PyPDF2 import PdfReader
from PIL import Image
import pytesseract


def extract_text_from_file(uploaded_file) -> str:
    file_type = uploaded_file.name.split('.')[-1].lower()
    
    if file_type == 'pdf':
        return extract_text_from_pdf(uploaded_file)
    elif file_type in ['jpg', 'jpeg', 'png']:
        return extract_text_from_image(uploaded_file)
    elif file_type == 'txt':
        return extract_text_from_txt(uploaded_file)
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def extract_text_from_pdf(uploaded_file) -> str:
    pdf_reader = PdfReader(uploaded_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text() + "\n"
    return text


def extract_text_from_image(uploaded_file) -> str:
    image = Image.open(uploaded_file)
    text = pytesseract.image_to_string(image, lang='kor+eng')
    return text


def extract_text_from_txt(uploaded_file) -> str:
    return uploaded_file.getvalue().decode('utf-8')
