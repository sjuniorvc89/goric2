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

# --- LÓGICA DEL BOT (Igual a la original) ---
async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # (Tu lógica de OCR y Sheets aquí...)
    await update.message.reply_text("Imagen recibida, procesando...")
    # ... resto del código ...

if __name__ == '__main__':
    # 1. Iniciamos Flask en un hilo separado para que Render esté feliz
    threading.Thread(target=run_flask, daemon=True).start()
    
    # 2. Iniciamos el Bot de Telegram en modo Polling (más fácil en Render)
    print(f"Iniciando Bot en puerto {PORT}...")
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    
    # run_polling bloquea el hilo principal, manteniendo el contenedor vivo
    application.run_polling()
