FROM python:3.11-slim

# Instalar Tesseract OCR y dependencias de sistema
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    && apt-get clean

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# El puerto que Render te da por defecto
EXPOSE 10000

CMD ["python", "app.py"]
