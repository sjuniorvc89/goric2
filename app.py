import logging
import os
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
TOKEN = "8786440728:AAHtUY0RuhIrBoCZYYFw49E2SLkMo7GKA30"
GOOGLE_SHEETS_CREDENTIALS = "creds.json"
SPREADSHEET_NAME = "Cordenadas"

# Render asigna un puerto automáticamente en la variable de entorno PORT
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(level=logging.INFO)

# --- WEB PARA RENDER (FLASK) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot Goric activo", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔎 1. Descargando imagen...")
    try:
        # Paso 1: Descarga
        photo = await update.message.photo[-1].get_file()
        img_bytes = await photo.download_as_bytearray()
        img = Image.open(BytesIO(img_bytes))
        
        await msg.edit_text("⚙️ 2. Ejecutando OCR (Tesseract)...")
        # Paso 2: OCR
        text = pytesseract.image_to_string(img)
        
        if not text.strip():
            await msg.edit_text("⚠️ OCR terminado pero no se encontró texto.")
            return

        await msg.edit_text("📊 3. Guardando en Google Sheets...")
        # Paso 3: Sheets
        gc = gspread.service_account(filename=GOOGLE_SHEETS_CREDENTIALS)
        sh = gc.open(SPREADSHEET_NAME)
        ws = sh.sheet1
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text[:500]])
        
        await msg.edit_text(f"✅ ¡Todo listo!\n\n**Texto extraído:**\n{text[:300]}")
        
    except Exception as e:
        import traceback
        error_full = traceback.format_exc()
        logging.error(error_full)
        await msg.edit_text(f"❌ Error en el paso actual:\n{str(e)}")

if __name__ == '__main__':
    # Arrancar Flask en hilo separado
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Arrancar Bot con parámetros de recuperación
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    
    print("Iniciando Bot Goric en Render...")
    
    # Usamos estos parámetros para forzar a que ignore errores de sesión vieja
    application.run_polling(drop_pending_updates=True, close_loop=False)
