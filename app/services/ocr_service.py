import io
import easyocr
import numpy as np
from PIL import Image

print("[ocr] Initializing EasyOCR Engine...")
# Initialize the reader for English
reader = easyocr.Reader(['en'])

def extract_text_from_image(image_bytes: bytes) -> str:
    """Converts uploaded image bytes into a numpy array and extracts text using EasyOCR."""
    try:
        # Convert raw bytes to PIL Image, then to numpy array for EasyOCR
        image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        image_np = np.array(image)
        
        # Extract text list
        extracted_text_list = reader.readtext(image_np, detail=0)
        
        # Join into a single string
        return " ".join(extracted_text_list)
    except Exception as e:
        raise ValueError(f"Failed to process image for OCR: {str(e)}")