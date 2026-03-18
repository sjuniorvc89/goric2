import logging
import os
import re
import json
import threading
from io import BytesIO
from datetime import datetime

import pytesseract
from PIL import Image
import gspread
from pyproj import Proj  # <- IMPORTANTE PARA CONVERTIR COORDENADAS
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Cordenadas")
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)

# --- WEB PARA RENDER (FLASK) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot Goric activo con OCR y Maps", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- FUNCIONES DE EXTRACCIÓN ---

def extract_specific_data(text):
    data = {
        'zone': None,
        'northing': None,
        'easting': None,
        'height': None
    }

    zone_pattern = r"Zone[^\d\n]*(\d+\s*[A-Za-z]?)"
    zone_match = re.search(zone_pattern, text, re.IGNORECASE)
    if zone_match:
        data['zone'] = zone_match.group(1).strip()

    northing_pattern = r"Northing[^\d\n]*([\d\.,]+)"
    northing_match = re.search(northing_pattern, text, re.IGNORECASE)
    if northing_match:
        data['northing'] = northing_match.group(1).strip()

    easting_pattern = r"Easting[^\d\n]*([\d\.,]+)"
    easting_match = re.search(easting_pattern, text, re.IGNORECASE)
    if easting_match:
        data['easting'] = easting_match.group(1).strip()

    height_pattern = r"Ellip[^\d\n]*([\d\.,]+\s*m?)"
    height_match = re.search(height_pattern, text, re.IGNORECASE)
    if height_match:
        data['height'] = height_match.group(1).strip()

    return data

# --- MANEJADOR DE IMÁGENES ---

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📸 Imagen recibida. Extrayendo datos y calculando ubicación...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        img = Image.open(BytesIO(img_bytes))
        
        # Ejecutar OCR
        text_ocr = pytesseract.image_to_string(img)
        
        if not text_ocr.strip():
            await msg.edit_text("⚠️ No se detectó texto en la imagen.")
            return

        # Extracción de datos
        extracted_data = extract_specific_data(text_ocr)

        if not any(extracted_data.values()):
             logging.info(f"TEXTO OCR CRUDO:\n{text_ocr}")
             await msg.edit_text("⚠️ No se encontraron los datos. Verifica la nitidez de la imagen.")
             return

        # --- CÁLCULO DE LAT/LON Y GOOGLE MAPS ---
        maps_link = "No disponible"
        if extracted_data['zone'] and extracted_data['northing'] and extracted_data['easting']:
            try:
                # Extraer solo el número de la zona (ej: "18 L" -> 18)
                zone_match = re.search(r'(\d+)', extracted_data['zone'])
                if zone_match:
                    zone_num = int(zone_match.group(1))
                    # Limpiar comas por si acaso y convertir a float
                    easting_val = float(extracted_data['easting'].replace(',', ''))
                    northing_val = float(extracted_data['northing'].replace(',', ''))
                    
                    # Convertir UTM a Lat/Lon (WGS84, asumiendo hemisferio sur)
                    p = Proj(proj='utm', zone=zone_num, ellps='WGS84', south=True)
                    lon, lat = p(easting_val, northing_val, inverse=True)
                    
                    maps_link = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
            except Exception as e:
                logging.error(f"Error convirtiendo coordenadas: {e}")

        # --- GUARDAR EN GOOGLE SHEETS ---
        await msg.edit_text("📊 Conectando con Google Sheets...")
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        if not creds_json:
            raise Exception("No se encontró la variable GOOGLE_CREDS_JSON en Render")

        creds_data = json.loads(creds_json)
        if "private_key" in creds_data:
            creds_data["private_key"] = creds_data["private_key"].replace("\\n", "\n")

        gc = gspread.service_account_from_dict(creds_data)
        sh = gc.open(SPREADSHEET_NAME)
        ws = sh.sheet1
        
        # Actualizamos las cabeceras para incluir Google Maps
        if len(ws.get_all_values()) == 0:
            ws.append_row(["Fecha Procesamiento", "Zone", "Northing", "Easting", "Ellip. Height", "Google Maps"])

        timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        row_to_append = [
            timestamp_now,
            extracted_data['zone'] if extracted_data['zone'] else 'No encontrado',
            extracted_data['northing'] if extracted_data['northing'] else 'No encontrado',
            extracted_data['easting'] if extracted_data['easting'] else 'No encontrado',
            extracted_data['height'] if extracted_data['height'] else 'No encontrado',
            maps_link  # <- AQUÍ SE GUARDA EL ENLACE EN LA NUEVA COLUMNA
        ]
        
        ws.append_row(row_to_append)
        
        # --- RESPUESTA EN TELEGRAM ---
        resumen = "✅ **¡Datos extraídos y guardados con éxito!**\n\n"
        resumen += f"🌐 Zone: `{row_to_append[1]}`\n"
        resumen += f"⬆️ Northing: `{row_to_append[2]}`\n"
        resumen += f"➡️ Easting: `{row_to_append[3]}`\n"
        resumen += f"🏔️ Height: `{row_to_append[4]}`\n"
        if maps_link != "No disponible":
            resumen += f"🗺️ **Google Maps:** [📍 Abrir Ubicación]({maps_link})"
        
        # Desactivamos la vista previa del enlace para que el mensaje no se vea gigante
        await msg.edit_text(resumen, parse_mode='Markdown', disable_web_page_preview=True)

    except Exception as e:
        logging.error(f"Error en el proceso: {e}")
        try:
            await msg.edit_text(f"❌ Error durante el procesamiento: {str(e)}")
        except:
            pass

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    print("Iniciando Bot Goric...")
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.run_polling(drop_pending_updates=True)
