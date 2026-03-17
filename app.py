import logging
import re
import os
from io import BytesIO
from datetime import datetime
import pytesseract
from PIL import Image
import gspread
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# --- CONFIGURACIÓN ---
TOKEN = "8786440728:AAHtUY0RuhIrBoCZYYFw49E2SLkMo7GKA30"
GOOGLE_SHEETS_CREDENTIALS = "creds.json"
SPREADSHEET_NAME = "Cordenadas"

logging.basicConfig(level=logging.INFO)

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🔎 Procesando imagen...")
    try:
        # Descarga
        photo = await update.message.photo[-1].get_file()
        img_bytes = await photo.download_as_bytearray()
        img = Image.open(BytesIO(img_bytes))
        
        # OCR
        text = pytesseract.image_to_string(img)
        
        # Google Sheets
        gc = gspread.service_account(filename=GOOGLE_SHEETS_CREDENTIALS)
        ws = gc.open(SPREADSHEET_NAME).sheet1
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text[:100]]) # Ejemplo simple
        
        await msg.edit_text(f"✅ Guardado. Texto detectado:\n{text[:200]}")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)}")

if __name__ == '__main__':
    # Render necesita que algo escuche en un puerto, aunque sea un bot
    from flask import Flask
    import threading
    app = Flask(__name__)
    @app.route('/')
    def health(): return "Vivo"
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))).start()

    # Iniciar Bot
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.run_polling()
