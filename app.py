import logging
import re
import asyncio
from io import BytesIO
from datetime import datetime

import pytesseract
from PIL import Image
import gspread
from pyproj import Proj
from flask import Flask, request
from telegram import Bot

# --- CONFIGURACIÓN ---
TOKEN = "8786440728:AAHtUY0RuhIrBoCZYYFw49E2SLkMo7GKA30"
GOOGLE_SHEETS_CREDENTIALS = "creds.json"
SPREADSHEET_NAME = "Cordenadas"

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
bot = Bot(token=TOKEN)

REGEX_PATTERNS = {
    "Zone": r"Zone[^\d\n]*(\d+[ \t]*[A-Za-z]?)",
    "Northing": r"Northing[^\d\n]*([0-9.,]+)",
    "Easting": r"Easting[^\d\n]*([0-9.,]+)",
    "Ellip. Height": r"Ellip[^\d\n]*([0-9.,]+\s*m?)"
}

async def process_image_logic(chat_id, photo_data):
    try:
        # 1. Descargar imagen
        file = await bot.get_file(photo_data.file_id)
        image_stream = BytesIO()
        await file.download_to_memory(out=image_stream)
        image_stream.seek(0)
        
        # 2. OCR
        img = Image.open(image_stream)
        extracted_text = pytesseract.image_to_string(img)
        
        results = {}
        for key, pattern in REGEX_PATTERNS.items():
            match = re.search(pattern, extracted_text, re.IGNORECASE)
            results[key] = match.group(1).strip() if match else "No encontrado"
        
        # 3. Google Sheets
        try:
            gc = gspread.service_account(filename=GOOGLE_SHEETS_CREDENTIALS)
            ws = gc.open(SPREADSHEET_NAME).sheet1
            ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), results['Zone'], results['Northing'], results['Easting'], results['Ellip. Height']])
            status = "✅ Guardado en Sheets."
        except Exception as e:
            status = f"⚠️ Error Sheets: {str(e)}"

        # 4. Responder
        await bot.send_message(chat_id=chat_id, text=f"{status}\nZ: {results['Zone']}\nN: {results['Northing']}\nE: {results['Easting']}")
        
    except Exception as e:
        logging.error(f"Error: {e}")
        await bot.send_message(chat_id=chat_id, text=f"❌ Error procesando: {str(e)}")

@app.route('/')
def home():
    return "Servidor Goric2 Ligero Activo"

@app.route('/webhook', methods=['POST'])
def webhook_handler():
    data = request.get_json(force=True)
    if "message" in data and "photo" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        photo = data["message"]["photo"][-1] # La de mejor calidad
        
        # Ejecutar el proceso en el hilo de eventos
        asyncio.run(process_image_logic(chat_id, photo))
        
    return "OK", 200

if __name__ == '__main__':
    print("Iniciando servidor Goric2 (Modo Ultra-Ligero)...")
    app.run(host='0.0.0.0', port=7860)
