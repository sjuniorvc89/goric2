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
USER_STATES = {}
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
    chat_id = update.effective_chat.id
    
    # Revisamos en qué paso está el usuario (por defecto: 'ESPERANDO_OCR')
    estado_actual = USER_STATES.get(chat_id, {}).get('state', 'ESPERANDO_OCR')

    # ======================================================
    # PASO 1: RECIBE LA CAPTURA Y EXTRAE COORDENADAS
    # ======================================================
    if estado_actual == 'ESPERANDO_OCR':
        msg = await update.message.reply_text("📸 Captura recibida. Leyendo coordenadas...")
        
        # 1. Descarga y OCR (igual que antes)
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        img = Image.open(BytesIO(img_bytes))
        text_ocr = pytesseract.image_to_string(img)
        
        extracted_data = extract_specific_data(text_ocr)

        if not any(extracted_data.values()):
             await msg.edit_text("⚠️ No pude leer las coordenadas. Intenta enviar la captura de nuevo.")
             return

        # 2. Guardamos los datos en la memoria temporal del bot y cambiamos el estado
        USER_STATES[chat_id] = {
            'state': 'ESPERANDO_FOTO',
            'datos_ocr': extracted_data
        }
        
        await msg.edit_text("✅ **¡Coordenadas leídas con éxito!**\n\n📸 Ahora, por favor envíame la **foto del lugar/evidencia**.")


    # ======================================================
    # PASO 2: RECIBE LA FOTO DE EVIDENCIA Y GUARDA TODO
    # ======================================================
    elif estado_actual == 'ESPERANDO_FOTO':
        msg = await update.message.reply_text("⏳ Subiendo evidencia y guardando en Google Sheets...")
        try:
            # 1. Recuperamos los datos que guardamos en el Paso 1
            extracted_data = USER_STATES[chat_id]['datos_ocr']
            
            # 2. Descargamos la nueva foto (Evidencia)
            photo_file = await update.message.photo[-1].get_file()
            img_bytes = await photo_file.download_as_bytearray()
            
            # 3. Subimos la foto a Telegraph para obtener un enlace público
            foto_url = "No disponible"
            try:
                files = {'file': ('evidencia.jpg', img_bytes, 'image/jpeg')}
                upload_res = requests.post('https://telegra.ph/upload', files=files).json()
                if isinstance(upload_res, list) and 'src' in upload_res[0]:
                    foto_url = 'https://telegra.ph' + upload_res[0]['src']
            except Exception as e:
                logging.error(f"Error subiendo foto: {e}")

            # 4. Calculamos Google Maps (como ya lo tenías)
            maps_link = "No disponible"
            if extracted_data['zone'] and extracted_data['northing']:
                try:
                    zone_match = re.search(r'(\d+)', extracted_data['zone'])
                    if zone_match:
                        zone_num = int(zone_match.group(1))
                        easting_val = float(extracted_data['easting'].replace(',', ''))
                        northing_val = float(extracted_data['northing'].replace(',', ''))
                        p = Proj(proj='utm', zone=zone_num, ellps='WGS84', south=True)
                        lon, lat = p(easting_val, northing_val, inverse=True)
                        maps_link = f"https://www.google.com/maps?q={lat:.6f},{lon:.6f}"
                except Exception:
                    pass

            # 5. Conectamos a Google Sheets
            creds_json = os.environ.get("GOOGLE_CREDS_JSON")
            creds_data = json.loads(creds_json)
            if "private_key" in creds_data:
                creds_data["private_key"] = creds_data["private_key"].replace("\\n", "\n")

            gc = gspread.service_account_from_dict(creds_data)
            sh = gc.open(SPREADSHEET_NAME)
            ws = sh.sheet1
            
            # Creamos cabeceras si está vacío (Añadimos la columna "Foto")
            if len(ws.get_all_values()) == 0:
                ws.append_row(["Fecha", "Zone", "Northing", "Easting", "Height", "Google Maps", "Foto", "Enlace Foto"])

            # 6. Preparamos la fila. Usamos la fórmula =IMAGE() para que Sheets muestre la foto
            timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formula_imagen = f'=IMAGE("{foto_url}")' if foto_url != "No disponible" else "Sin foto"

            row_to_append = [
                timestamp_now,
                extracted_data['zone'],
                extracted_data['northing'],
                extracted_data['easting'],
                extracted_data['height'],
                maps_link,
                formula_imagen,  # Esto mostrará la imagen en la celda
                foto_url         # Esto guarda el enlace directo por si acaso
            ]
            
            # IMPORTANTE: value_input_option='USER_ENTERED' permite que Sheets lea la fórmula =IMAGE()
            ws.append_row(row_to_append, value_input_option='USER_ENTERED')
            
            # 7. Borramos la memoria para que el usuario pueda enviar una nueva captura
            del USER_STATES[chat_id]
            
            # 8. Mensaje final
            resumen = "✅ **¡Registro completo y guardado!**\n\n"
            resumen += f"📍 **Maps:** [Abrir Ubicación]({maps_link})\n"
            resumen += f"🖼️ **Foto:** [Ver Evidencia]({foto_url})"
            
            await msg.edit_text(resumen, parse_mode='Markdown', disable_web_page_preview=True)

        except Exception as e:
            logging.error(f"Error en el guardado final: {e}")
            await msg.edit_text("❌ Ocurrió un error al guardar. Intentemos desde el principio (envía la captura de coordenadas de nuevo).")
            # En caso de error, reiniciamos el estado para no dejarlo atascado
            if chat_id in USER_STATES:
                del USER_STATES[chat_id]

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    print("Iniciando Bot Goric...")
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.run_polling(drop_pending_updates=True)
