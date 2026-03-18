import logging
import os
import json
import re
import threading
from io import BytesIO
from datetime import datetime

import pytesseract
from PIL import Image
import gspread
from pyproj import Proj
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- CONFIGURACIÓN ---
# Recuperar variables de entorno de Render (Establece estas en el panel de Render)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Cordenadas")
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)

# --- CONFIGURACIÓN DE PROYECCIÓN (UTM) ---
# Adaptado del archivo subido
# Se asume WGS84, Zona 18 Sur (Ajustar si es necesario)
myProj = Proj("+proj=utm +zone=18 +south +ellps=WGS84 +datum=WGS84 +units=m +no_defs")

# --- WEB PARA RENDER (FLASK) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot Goric activo con Extracción", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- FUNCIONES DE EXTRACCIÓN Y TRANSFORMACIÓN (Adaptadas del archivo subido) ---

def transform_wgs84_to_utm(lon, lat):
    """Transforma coordenadas WGS84 (lat/lon) a UTM."""
    try:
        easting, northing = myProj(lon, lat)
        return easting, northing
    except Exception as e:
        logging.error(f"Error en transformación UTM: {e}")
        return None, None

def extract_data_from_text(text):
    """
    Busca patrones específicos en el texto OCR usando regex.
    Retorna un diccionario con los datos encontrados.
    """
    data = {
        'coordenadas': None,
        'nombre_foto': None,
        'fecha': None,
        'hora': None
    }

    # --- PATRONES REGEX (Basados en el archivo app.py subido) ---
    
    # 1. Coordenadas (Busca formatos tipo: "Coordenadas: 12.3456, -78.9012" o similares)
    # Este patrón es flexible para capturar números decimales
    coord_pattern = r"Coordenadas:\s*([-+]?\d*\.\d+|\d+)\s*,\s*([-+]?\d*\.\d+|\d+)"
    coord_match = re.search(coord_pattern, text, re.IGNORECASE)
    if coord_match:
        data['coordenadas'] = coord_match.group(1) + ", " + coord_match.group(2)

    # 2. Nombre de la foto (Busca patrones tipo: "P_20231027_103005" o similares)
    photo_pattern = r"P_(\d{8})_(\d{6})"
    photo_match = re.search(photo_pattern, text, re.IGNORECASE)
    if photo_match:
        # Reconstruye el nombre completo si es necesario, aquí solo capturamos los grupos
        data['nombre_foto'] = "P_" + photo_match.group(1) + "_" + photo_match.group(2)

    # 3. Fecha (Formatos comunes: DD/MM/AAAA, AA/MM/DD, etc. Se busca DD/MM/AAAA primero)
    date_pattern = r"(\d{1,2}/\d{1,2}/\d{4})"
    date_match = re.search(date_pattern, text)
    if date_match:
        data['fecha'] = date_match.group(1)

    # 4. Hora (Formatos: HH:MM:SS o HH:MM)
    time_pattern = r"(\d{1,2}:\d{2}(?::\d{2})?)"
    time_match = re.search(time_pattern, text)
    if time_match:
        data['hora'] = time_match.group(1)

    return data

# --- MANEJADOR DE IMÁGENES (Lógica Principal) ---

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📸 Imagen recibida. Procesando e intentando extraer datos...")
    try:
        # 1. DESCARGA Y PROCESAMIENTO DE IMAGEN
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        img = Image.open(BytesIO(img_bytes))
        
        # 2. EJECUCIÓN DEL OCR (Tesseract)
        await msg.edit_text("⚙️ Extrayendo texto general...")
        text_ocr = pytesseract.image_to_string(img)
        
        if not text_ocr.strip():
            await msg.edit_text("⚠️ No se detectó texto legible en la imagen. No se guardará nada.")
            return

        # 3. EXTRACCIÓN DE DATOS ESPECÍFICOS (Lógica adaptada)
        await msg.edit_text("🔍 Buscando coordenadas, fecha, hora y nombre de foto...")
        extracted_data = extract_data_from_text(text_ocr)

        # 4. AUTENTICACIÓN CON GOOGLE SHEETS (Lógica funcional en Render)
        await msg.edit_text("📊 Conectando con Google Sheets...")
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_json:
            raise Exception("No se encontró la variable GOOGLE_CREDS_JSON en Render")

        creds_data = json.loads(creds_json)
        # Limpieza de la llave private_key (Vital para Render)
        if "private_key" in creds_data:
            creds_data["private_key"] = creds_data["private_key"].replace("\\n", "\n")

        # 5. GUARDADO DE DATOS ESTRUCTURADOS
        gc = gspread.service_account_from_dict(creds_data)
        sh = gc.open(SPREADSHEET_NAME)
        ws = sh.sheet1
        
        # Prepara la fila con los datos extraídos (o 'No encontrado')
        timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        row_to_append = [
            timestamp_now,
            extracted_data['nombre_foto'] if extracted_data['nombre_foto'] else 'No encontrado',
            extracted_data['fecha'] if extracted_data['fecha'] else 'No encontrado',
            extracted_data['hora'] if extracted_data['hora'] else 'No encontrado',
            extracted_data['coordenadas'] if extracted_data['coordenadas'] else 'No encontrado',
            text_ocr[:2000] # Guardamos el OCR completo al final, limitado a 2000 caracteres
        ]
        
        ws.append_row(row_to_append)
        
        # 6. MENSAJE DE ÉXITO AL USUARIO
        # Construimos un resumen de lo encontrado
        resumen = "✅ **¡Datos guardados con éxito!**\n\n**Resumen de extracción:**\n"
        resumen += f"🏷️ Foto: `{row_to_append[1]}`\n"
        resumen += f"📅 Fecha: `{row_to_append[2]}`\n"
        resumen += f"🕒 Hora: `{row_to_append[3]}`\n"
        resumen += f"📍 Coords: `{row_to_append[4]}`\n"
        
        await msg.edit_text(resumen, parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Error en el proceso: {e}")
        # En caso de error, intentamos editar el mensaje o enviar uno nuevo
        try:
            await msg.edit_text(f"❌ Error durante el procesamiento: {str(e)}")
        except:
            await update.message.reply_text(f"❌ Error crítico: {str(e)}")

# --- INICIO DE LA APLICACIÓN ---

if __name__ == '__main__':
    # Hilo para el servidor web Flask (necesario para Render)
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Iniciar la aplicación de Telegram (modo Polling, funcional en Render)
    print("Iniciando Bot Goric con extracción de datos...")
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    
    # run_polling bloquea el hilo principal, manteniendo el bot vivo
    application.run_polling(drop_pending_updates=True)
