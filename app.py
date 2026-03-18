import logging
import os
import re
import json
import threading
import requests
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
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Cordenadas")
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)

# --- ESTADOS DEL BOT (Memoria) ---
USER_STATES = {}

# --- WEB PARA RENDER (FLASK) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot Goric activo con OCR y Subida de Fotos Robusta", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- FUNCIONES DE EXTRACCIÓN ---
def extract_specific_data(text):
    data = {'zone': None, 'northing': None, 'easting': None, 'height': None}
    
    zone_match = re.search(r"Zone[^\d\n]*(\d+\s*[A-Za-z]?)", text, re.IGNORECASE)
    if zone_match: data['zone'] = zone_match.group(1).strip()

    northing_match = re.search(r"Northing[^\d\n]*([\d\.,]+)", text, re.IGNORECASE)
    if northing_match: data['northing'] = northing_match.group(1).strip()

    easting_match = re.search(r"Easting[^\d\n]*([\d\.,]+)", text, re.IGNORECASE)
    if easting_match: data['easting'] = easting_match.group(1).strip()

    height_match = re.search(r"Ellip[^\d\n]*([\d\.,]+\s*m?)", text, re.IGNORECASE)
    if height_match: data['height'] = height_match.group(1).strip()

    return data

# --- MANEJADOR PRINCIPAL DE IMÁGENES ---
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    estado_actual = USER_STATES.get(chat_id, {}).get('state', 'ESPERANDO_OCR')

    # ==========================================
    # PASO 1: LEER LA CAPTURA (OCR)
    # ==========================================
    if estado_actual == 'ESPERANDO_OCR':
        msg = await update.message.reply_text("📸 Captura recibida. Leyendo coordenadas...")
        try:
            photo_file = await update.message.photo[-1].get_file()
            img_bytes = await photo_file.download_as_bytearray()
            img = Image.open(BytesIO(img_bytes))
            
            text_ocr = pytesseract.image_to_string(img)
            extracted_data = extract_specific_data(text_ocr)

            if not any(extracted_data.values()):
                 await msg.edit_text("⚠️ No pude leer las coordenadas. Intenta enviar la captura de nuevo con más nitidez.")
                 return

            # Guardamos en memoria y pasamos al Paso 2
            USER_STATES[chat_id] = {
                'state': 'ESPERANDO_FOTO',
                'datos_ocr': extracted_data
            }
            
            await msg.edit_text("✅ **¡Coordenadas leídas!**\n\n📸 Ahora, envíame la **foto del lugar/evidencia** para adjuntarla.")

        except Exception as e:
            logging.error(f"Error en OCR: {e}")
            await msg.edit_text("❌ Ocurrió un error leyendo la imagen.")

    # ==========================================
    # PASO 2: RECIBIR EVIDENCIA Y GUARDAR EN SHEETS
    # ==========================================
    elif estado_actual == 'ESPERANDO_FOTO':
        msg = await update.message.reply_text("⏳ Subiendo foto y guardando el registro completo...")
        try:
            extracted_data = USER_STATES[chat_id]['datos_ocr']
            
            # 1. Descargar la nueva foto
            photo_file = await update.message.photo[-1].get_file()
            img_bytes = await photo_file.download_as_bytearray()
            
            # 2. SUBIDA DE IMAGEN ROBUSTA (Plan A y Plan B)
            foto_url = "No disponible"
            
            # Plan A: Intentar con Catbox.moe (No bloquea a Render)
            try:
                url_catbox = "https://catbox.moe/user/api.php"
                data_catbox = {"reqtype": "fileupload"}
                # Usamos BytesIO para que el servidor lo reconozca como un archivo real
                files_catbox = {"fileToUpload": ("evidencia.jpg", BytesIO(img_bytes), "image/jpeg")}
                res_catbox = requests.post(url_catbox, data=data_catbox, files=files_catbox)
                
                if res_catbox.status_code == 200 and res_catbox.text.startswith("http"):
                    foto_url = res_catbox.text
            except Exception as e:
                logging.error(f"Catbox falló: {e}")

            # Plan B: Si Catbox falla, intentar con Telegra.ph
            if foto_url == "No disponible":
                try:
                    files_tele = {'file': ('evidencia.jpg', BytesIO(img_bytes), 'image/jpeg')}
                    res_tele = requests.post('https://telegra.ph/upload', files=files_tele).json()
                    if isinstance(res_tele, list) and 'src' in res_tele[0]:
                        foto_url = 'https://telegra.ph' + res_tele[0]['src']
                except Exception as e:
                    logging.error(f"Telegraph falló: {e}")

            # 3. Calcular Google Maps
            maps_link = "No disponible"
            if extracted_data['zone'] and extracted_data['northing'] and extracted_data['easting']:
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

            # 4. Conectar a Google Sheets
            creds_json = os.environ.get("GOOGLE_CREDS_JSON")
            creds_data = json.loads(creds_json)
            if "private_key" in creds_data:
                creds_data["private_key"] = creds_data["private_key"].replace("\\n", "\n")

            gc = gspread.service_account_from_dict(creds_data)
            sh = gc.open(SPREADSHEET_NAME)
            ws = sh.sheet1
            
            # Crear cabeceras si la hoja está vacía
            if len(ws.get_all_values()) == 0:
                ws.append_row(["Fecha", "Zone", "Northing", "Easting", "Height", "Google Maps", "Previsualización", "Enlace Foto"])

            # 5. Guardar los datos. =IMAGE() hace que la foto se vea en la celda
            timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            formula_imagen = f'=IMAGE("{foto_url}")' if foto_url != "No disponible" else "Sin foto"

            row_to_append = [
                timestamp_now,
                extracted_data['zone'] if extracted_data['zone'] else 'No encontrado',
                extracted_data['northing'] if extracted_data['northing'] else 'No encontrado',
                extracted_data['easting'] if extracted_data['easting'] else 'No encontrado',
                extracted_data['height'] if extracted_data['height'] else 'No encontrado',
                maps_link,
                formula_imagen,
                foto_url
            ]
            
            # 'USER_ENTERED' es obligatorio para que Google Sheets procese la fórmula =IMAGE
            ws.append_row(row_to_append, value_input_option='USER_ENTERED')
            
            # 6. Limpiar la memoria para el próximo registro
            del USER_STATES[chat_id]
            
            # 7. Responder al usuario
            resumen = "✅ **¡Registro completo y guardado con éxito!**\n\n"
            resumen += f"🌐 Zone: `{row_to_append[1]}`\n"
            resumen += f"⬆️ Northing: `{row_to_append[2]}`\n"
            resumen += f"➡️ Easting: `{row_to_append[3]}`\n"
            resumen += f"🏔️ Height: `{row_to_append[4]}`"
            resumen += f"📍 **Ubicación:** [Abrir en Maps]({maps_link})\n"
            if foto_url != "No disponible":
                resumen += f"🖼️ **Evidencia:** [Ver Foto]({foto_url})"
            else:
                resumen += "\n⚠️ *(Nota: No se pudo subir la foto por restricciones del servidor externo)*"
            
            await msg.edit_text(resumen, parse_mode='Markdown', disable_web_page_preview=True)

        except Exception as e:
            logging.error(f"Error en el Paso 2: {e}")
            await msg.edit_text("❌ Error al guardar. Se ha cancelado el proceso, envía la captura de coordenadas para intentar de nuevo.")
            if chat_id in USER_STATES:
                del USER_STATES[chat_id]

# --- INICIO ---
if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    print("Iniciando Bot Goric en 2 Pasos...")
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.run_polling(drop_pending_updates=True)
