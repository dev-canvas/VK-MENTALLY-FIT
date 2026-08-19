import asyncio
import logging
import os
import random
from datetime import datetime
from pathlib import Path

import aiosqlite
import requests  # <-- Новая библиотека вместо vk_api
from PIL import Image, ImageDraw, ImageFont
import pytz

from affirmations_list import AFFIRMATIONS

# --- КОНФИГУРАЦИЯ ---
TZ_NAME = "Europe/Moscow"
tz = pytz.timezone(TZ_NAME)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "affirmations.db"
FONTS_DIR = BASE_DIR / "fonts"
LOG_FILE = LOGS_DIR / "run.log"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Настройка логирования
def setup_logging():
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(formatter)
    
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger

logger = setup_logging()

# Получаем токен и ID группы из секретов GitHub
VK_TOKEN = os.getenv("VK_TOKEN")
VK_OWNER_ID = int(os.getenv("VK_OWNER_ID"))  # Например, -123456789

if not VK_TOKEN or not VK_OWNER_ID:
    logger.error("❌ Не найдены переменные окружения VK_TOKEN или VK_OWNER_ID!")
    raise SystemExit(1)

def get_font():
    font_path = FONTS_DIR / "TTNormsPro-Thin.ttf"
    if font_path.exists():
        return ImageFont.truetype(str(font_path), 60)
    else:
        logger.warning("Шрифт не найден, используется стандартный.")
        return ImageFont.load_default()

async def init_db():
    if not DB_PATH.exists():
        logger.info("База данных не найдена. Создаю новую...")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS affirmations (
                    id INTEGER PRIMARY KEY,
                    text TEXT NOT NULL,
                    image_id INTEGER DEFAULT 1,
                    used INTEGER DEFAULT 0
                )
            """)
            for i, text in enumerate(AFFIRMATIONS, start=1):
                await db.execute(
                    "INSERT INTO affirmations (id, text, image_id, used)
