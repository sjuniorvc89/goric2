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
    # 1. Definimos msg al principio para evitar el NameError
    msg = await update.message.reply_text("📸 Imagen recibida. Procesando...")

    try:
        # 2. Descarga y OCR (Asegúrate de que este bloque esté completo)
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = await photo_file.download_as_bytearray()
        img = Image.open(BytesIO(img_bytes))
        
        await msg.edit_text("⚙️ Ejecutando OCR...")
        text = pytesseract.image_to_string(img)

        # 3. Uso de la variable de entorno de Render
        await msg.edit_text("📊 Conectando con Google Sheets...")
        
        # Obtenemos la variable que configuraste en la imagen de Render
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        
        if not creds_json:
            raise Exception("No se encontró la variable GOOGLE_CREDS_JSON en Render")

        creds_data = json.loads(creds_json)
        
        # Limpieza de la llave (Vital para evitar el error de firma JWT)
        if "private_key" in creds_data and "\\n" in creds_data["private_key"]:
            creds_data["private_key"] = creds_data["private_key"].replace("\\n", "\n")

        # 4. Autenticación y guardado
        gc = gspread.service_account_from_dict(creds_data)
        sh = gc.open(SPREADSHEET_NAME)
        ws = sh.sheet1
        
        ws.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), text[:500]])
        
        await msg.edit_text(f"✅ ¡Guardado exitosamente!\n\n**Texto extraído:**\n{text[:200]}...")

    except Exception as e:
        logging.error(f"Error en el proceso: {e}")
        # Ahora 'msg' siempre está disponible aquí
        await msg.edit_text(f"❌ Error: {str(e)}")

if __name__ == '__main__':
    # Arrancar Flask en hilo separado
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Arrancar Bot con parámetros de recuperación
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    
    print("Iniciando Bot Goric en Render...")
    
    # Usamos estos parámetros para forzar a que ignore errores de sesión vieja
    application.run_polling(drop_pending_updates=True, close_loop=False)
