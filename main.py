import asyncio
import logging
import os
import random
from datetime import datetime
from pathlib import Path

import aiosqlite
import requests
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
    # Очищаем старые хендлеры, чтобы не дублировать логи при повторных запусках в некоторых средах
    logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    return logger

logger = setup_logging()

# Получение переменных из GitHub Secrets
VK_TOKEN = os.getenv("VK_TOKEN")
VK_OWNER_ID_STR = os.getenv("VK_OWNER_ID")

if not VK_TOKEN:
    logger.critical("❌ Ошибка: Не найден секрет VK_TOKEN в настройках репозитория!")
    raise SystemExit(1)

if not VK_OWNER_ID_STR:
    logger.critical("❌ Ошибка: Не найден секрет VK_OWNER_ID в настройках репозитория!")
    raise SystemExit(1)

try:
    VK_OWNER_ID = int(VK_OWNER_ID_STR)
except ValueError:
    logger.critical("❌ Ошибка: VK_OWNER_ID должен быть числом (например, -123456789)")
    raise SystemExit(1)

def get_font():
    font_path = FONTS_DIR / "TTNormsPro-Thin.ttf"
    if font_path.exists():
        try:
            return ImageFont.truetype(str(font_path), 60)
        except Exception as e:
            logger.warning(f"Не удалось загрузить шрифт: {e}. Использую стандартный.")
            return ImageFont.load_default()
    else:
        logger.warning("Шрифт не найден, используется стандартный.")
        return ImageFont.load_default()

async def init_db():
    if not DB_PATH.exists():
        logger.info("База данных не найдена. Создаю новую...")
        async with aiosqlite.connect(DB_PATH) as db:
            # ИСПРАВЛЕНО: Тройные кавычки для многострочного SQL
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
                    "INSERT INTO affirmations (id, text, image_id, used) VALUES (?, ?, ?, 0)",
                    (i, text, i)
                )
            await db.commit()
        logger.info(f"✅ База данных создана с {len(AFFIRMATIONS)} аффирмациями.")
    else:
        # Проверка целостности: вдруг нет колонки used
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("PRAGMA table_info(affirmations)")
            columns = [col[1] for col in await cursor.fetchall()]
            if 'used' not in columns:
                logger.warning("Добавляем колонку 'used' в БД...")
                await db.execute("ALTER TABLE affirmations ADD COLUMN used INTEGER DEFAULT 0")
                await db.commit()
                logger.info("✅ Колонка 'used' добавлена.")
        logger.info("✅ База данных найдена и проверена.")

async def get_next_affirmation() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, text, image_id FROM affirmations WHERE used = 0 ORDER BY RANDOM() LIMIT 1")
        row = await cursor.fetchone()
        
        if not row:
            logger.warning("Все аффирмации использованы! Сбрасываем флаги.")
            await db.execute("UPDATE affirmations SET used = 0")
            cursor = await db.execute("SELECT id, text, image_id FROM affirmations ORDER BY RANDOM() LIMIT 1")
            row = await cursor.fetchone()
        
        aff_id, text, img_id = row
        await db.execute("UPDATE affirmations SET used = 1 WHERE id = ?", (aff_id,))
        await db.commit()
        
        logger.info(f"Выбрана аффирмация #{aff_id}: {text[:30]}...")
        return {"id": aff_id, "text": text, "image_id": img_id or 1}

def random_pastel_color():
    hue = random.random()
    sat = random.uniform(0.3, 0.5)
    light = random.uniform(0.8, 0.95)
    c = (1 - abs(2 * light - 1)) * sat
    x = c * (1 - abs((hue * 6) % 2 - 1))
    m = light - c / 2
    
    if 0 <= hue < 1/6: r, g, b = c, x, 0
    elif 1/6 <= hue < 2/6: r, g, b = x, c, 0
    elif 2/6 <= hue < 3/6: r, g, b = 0, c, x
    elif 3/6 <= hue < 4/6: r, g, b = 0, x, c
    elif 4/6 <= hue < 5/6: r, g, b = x, 0, c
    else: r, g, b = c, 0, x
    
    return tuple(int(255 * (v + m)) for v in (r, g, b))

async def generate_image(aff_text: str) -> str:
    img = Image.new('RGB', (800, 600), color=random_pastel_color())
    draw = ImageDraw.Draw(img)
    font = get_font()
    
    max_width = 760
    words = aff_text.split()
    lines = []
    current_line = []
    
    for word in words:
        test_line = ' '.join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if bbox[2] > max_width:
            if current_line:
                lines.append(' '.join(current_line))
                current_line = [word]
            else:
                lines.append(word)
        else:
            current_line.append(word)
    if current_line:
        lines.append(' '.join(current_line))
    
    line_height = 70
    total_height = len(lines) * line_height
    y_start = (600 - total_height) // 2
    
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (800 - text_width) // 2
        y = y_start + i * line_height
        draw.text((x, y), line, fill="black", font=font)
    
    temp_path = Path("/tmp") / f"aff_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    img.save(temp_path)
    return str(temp_path)

async def post_to_vk(aff: dict):
    """
    Загружает фото и публикует пост напрямую через API VK.
    Работает ТОЛЬКО с токеном сообщества.
    """
    photo_path = await generate_image(aff["text"])
    caption = (
        f"✨\n\n\n\nСтавь ❤️ и другой увидит, что он не один\n\n"
        f"@mentally_fit"
    )

    # ID группы без минуса нужен для методов загрузки фото
    group_id_clean = str(abs(VK_OWNER_ID))
    
    logger.info("📤 Получаем URL для загрузки фото...")
    upload_server_resp = requests.post(
        "https://api.vk.com/method/photos.getWallUploadServer",
        params={
            "group_id": group_id_clean,
            "access_token": VK_TOKEN,
            "v": "5.131"
        }
    ).json()

    if "error" in upload_server_resp:
        err = upload_server_resp.get("error", {}).get("error_msg", "Неизвестная ошибка")
        raise Exception(f"Ошибка получения сервера загрузки: {err}")

    upload_url = upload_server_resp["response"]["upload_url"]

    logger.info("🖼️ Загружаем фото на сервер VK...")
    with open(photo_path, "rb") as f:
        files = {"photo": f}
        upload_resp = requests.post(upload_url, files=files).json()

    if "error" in upload_resp:
        err = upload_resp.get("error", {}).get("error_msg", "Неизвестная ошибка")
        raise Exception(f"Ошибка загрузки файла: {err}")

    logger.info("💾 Сохраняем фото в группе...")
    save_resp = requests.post(
        "https://api.vk.com/method/photos.saveWallPhoto",
        data={
            "group_id": group_id_clean,
            "server": upload_resp["server"],
            "photo": upload_resp["photo"],
            "hash": upload_resp["hash"],
            "access_token": VK_TOKEN,
            "v": "5.131"
        }
    ).json()

    if "error" in save_resp:
        err = save_resp.get("error", {}).get("error_msg", "Неизвестная ошибка")
        raise Exception(f"Ошибка сохранения фото: {err}")

    photo_data = save_resp["response"][0]
    attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"

    logger.info("📢 Публикуем пост...")
    post_resp = requests.post(
        "https://api.vk.com/method/wall.post",
        data={
            "owner_id": VK_OWNER_ID,       # ID группы с минусом
            "from_group": 1,              # Пост от имени группы (ОБЯЗАТЕЛЬНО)
            "message": caption,
            "attachments": attachment,
            "access_token": VK_TOKEN,
            "v": "5.131"
        }
    ).json()

    if "error" in post_resp:
        err = post_resp.get("error", {}).get("error_msg", "Неизвестная ошибка")
        raise Exception(f"Ошибка публикации поста: {err}")

    logger.info(f"✅ Пост успешно опубликован! ID поста: {post_resp['response']['post_id']}")

async def main():
    moscow_time = datetime.now(tz)
    logger.info(f"Запуск скрипта. Текущее время (МСК): {moscow_time.strftime('%Y-%m-%d %H:%M')}")
    
    try:
        await init_db()
        aff = await get_next_affirmation()
        await post_to_vk(aff)
        logger.info("Задача успешно завершена.")
    except Exception as e:
        logger.critical(f"💥 Критическая ошибка: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    asyncio.run(main())
