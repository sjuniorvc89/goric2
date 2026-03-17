# 1. Usar una imagen de Python estable
FROM python:3.11-slim

# 2. Instalar dependencias del sistema (Tesseract y utilidades)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    pkg-config \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 3. Crear un usuario para que Hugging Face no corra como root
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:${PATH}"

# 4. Establecer el directorio de trabajo
WORKDIR /app

# 5. Copiar e instalar librerías de Python
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copiar el resto de los archivos (app.py, creds.json)
COPY --chown=user . .

# 7. Exponer el puerto que Hugging Face requiere (aunque sea un bot)
EXPOSE 7860

# 8. Comando para arrancar el bot
CMD ["python", "app.py"]
