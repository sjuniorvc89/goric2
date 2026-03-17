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
from pyproj import Proj
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- CONFIGURACIÓN ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "Cordenadas")

# Recuperar el JSON de Google desde una variable de entorno
creds_json = os.environ.get("GOOGLE_CREDS_JSON")

if creds_json:
    creds_data = json.loads(creds_json)
    # Limpieza de la llave como hicimos antes
    if "\\n" in creds_data['private_key']:
        creds_data['private_key'] = creds_data['private_key'].replace("\\n", "\n")
else:
    logging.error("No se encontró la variable GOOGLE_CREDS_JSON")


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
    # ... (pasos anteriores) ...

    try:
        # Cargar el archivo de credenciales manualmente para limpiar la llave
        with open(GOOGLE_SHEETS_CREDENTIALS, 'r') as f:
            creds_data = json.load(f)
        
        # LIMPIEZA CRÍTICA: Reemplaza saltos de línea mal formateados
        if "\\n" in creds_data['private_key']:
            creds_data['private_key'] = creds_data['private_key'].replace("\\n", "\n")
        
        # Autenticar con los datos corregidos
        gc = gspread.service_account_from_dict(creds_data)
        sh = gc.open(SPREADSHEET_NAME)
        ws = sh.sheet1
        
        # Guardar (ajusta 'text' según tu variable de OCR)
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text[:500]])
        
        await msg.edit_text("✅ ¡Guardado exitosamente en Google Sheets!")

    except Exception as e:
        logging.error(f"Error en Sheets: {e}")
        await msg.edit_text(f"❌ Error en Google Sheets: {str(e)}")

if __name__ == '__main__':
    # Arrancar Flask en hilo separado
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Arrancar Bot con parámetros de recuperación
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    
    print("Iniciando Bot Goric en Render...")
    
    # Usamos estos parámetros para forzar a que ignore errores de sesión vieja
    application.run_polling(drop_pending_updates=True, close_loop=False)
