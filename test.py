import re

def clean_ocr_text(text):
    # Remove unwanted leading characters before the valid format (letters followed by a number)
    text = re.sub(r'^[^A-Z]*([A-Z]{2,3}\s*\d{4})', r'\1', text)
    
    # Replace = or - with a space
    text = re.sub(r'[-=]', ' ', text)
    
    # Normalize multiple spaces into a single space
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

# Example usage:
ocr_texts = [
    "XY AB 1234", "XY ABC 1234", "XYAB 1234", "XYABC 1234", "AB-1234", "ABC=1234", "AB 1234", "ABC 1234", "ZZ AB 1234", "123 ABC 5678"
]

for text in ocr_texts:
    print(clean_ocr_text(text))