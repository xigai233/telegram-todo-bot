import os
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import psycopg2
from psycopg2.extras import RealDictCursor

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Get bot token from environment variable
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Global scheduler for reminders
scheduler = AsyncIOScheduler()

# Language texts
TEXTS = {
    'zh': {
        'welcome': '👋 歡迎使用待辦事項機器人！',
        'choose_language': '🌐 請選擇語言：',
        'main_menu': '🏠 主選單 - 請選擇操作：',
        'query_all': '📋 所有待辦事項',
        'query_category': '🔍 分類查詢',
        'add_todo': '📝 新增待辦',
        'change_language': '🌐 切換語言',
        'choose_category': '📂 請選擇類別：',
        'enter_task': '✏️ 請輸入待辦事項內容：',
        'need_reminder': '⏰ 需要設置提醒嗎？',
        'enter_reminder_time': '🕒 請輸入提醒時間（格式：HH:MM 或 幾小時後）：',
        'task_added': '✅ 已成功添加待辦事項！',
        'no_tasks': '📭 目前沒有待辦事項',
        'tasks_in_category': '📋 {}類別的待辦事項：',
        'all_tasks': '📋 所有待辦事項：',
        'reminder_set': '⏰ 已設置提醒於 {}',
        'invalid_time': '❌ 時間格式錯誤，請使用 HH:MM 格式',
        'category_game': '🎮 遊戲',
        'category_movie': '📺 影視',
        'category_action': '⭐ 行動'
    },
    'en': {
        'welcome': '👋 Welcome to Todo Bot!',
        'choose_language': '🌐 Please choose language:',
        'main_menu': '🏠 Main Menu - Please choose operation:',
        'query_all': '📋 All Todos',
        'query_category': '🔍 Query by Category',
        'add_todo': '📝 Add Todo',
        'change_language': '🌐 Change Language',
        'choose_category': '📂 Please choose category:',
        'enter_task': '✏️ Please enter todo content:',
        'need_reminder': '⏰ Do you need a reminder?',
        'enter_reminder_time': '🕒 Please enter reminder time (format: HH:MM or in X hours):',
        'task_added': '✅ Todo added successfully!',
        'no_tasks': '📭 No tasks at the moment',
        'tasks_in_category': '📋 Todos in {} category:',
        'all_tasks': '📋 All todos:',
        'reminder_set': '⏰ Reminder set for {}',
        'invalid_time': '❌ Invalid time format, please use HH:MM format',
        'category_game': '🎮 Games',
        'category_movie': '📺 Movies',
        'category_action': '⭐ Actions'
    }
}

# Categories
CATEGORIES = {
    'game': {'zh': '🎮 遊戲', 'en': '🎮 Games'},
    'movie': {'zh': '📺 影視', 'en': '📺 Movies'},
    'action': {'zh': '⭐ 行動', 'en': '⭐ Actions'}
}

# Database functions
def init_db():
    conn = sqlite3.connect('todo_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, language TEXT DEFAULT 'zh', 
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS todos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  user_id INTEGER, 
                  category TEXT,
                  task TEXT, 
                  reminder_time TIMESTAMP NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    conn.commit()
    conn.close()

def get_user_language(user_id):
    conn = sqlite3.connect('todo_bot.db')
    c = conn.cursor()
    c.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 'zh'

def set_user_language(user_id, language):
    conn = sqlite3.connect('todo_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, language) VALUES (?, ?)", 
              (user_id, language))
    conn.commit()
    conn.close()

def add_todo_to_db(user_id, category, task, reminder_time=None):
    conn = sqlite3.connect('todo_bot.db')
    c = conn.cursor()
    c.execute("INSERT INTO todos (user_id, category, task, reminder_time) VALUES (?, ?, ?, ?)",
              (user_id, category, task, reminder_time))
    conn.commit()
    todo_id = c.lastrowid
    conn.close()
    return todo_id

def get_todos(user_id, category=None):
    conn = sqlite3.connect('todo_bot.db')
    c = conn.cursor()
    if category:
        c.execute("SELECT category, task, reminder_time FROM todos WHERE user_id = ? AND category = ? ORDER BY created_at", 
                  (user_id, category))
    else:
        c.execute("SELECT category, task, reminder_time FROM todos WHERE user_id = ? ORDER BY created_at", 
                  (user_id,))
    todos = c.fetchall()
    conn.close()
    return todos

# Keyboard functions
def get_main_keyboard(language):
    text = TEXTS[language]
    return ReplyKeyboardMarkup([
        [text['query_all'], text['query_category']],
        [text['add_todo'], text['change_language']]
    ], resize_keyboard=True)

def get_category_keyboard(language):
    keyboard = []
    for category_id, category_names in CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(category_names[language], callback_data=f'category_{category_id}')])
    return InlineKeyboardMarkup(keyboard)

def get_reminder_keyboard(language):
    text = TEXTS[language]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ " + ("是" if language == 'zh' else "Yes"), callback_data='reminder_yes'),
         InlineKeyboardButton("❌ " + ("否" if language == 'zh' else "No"), callback_data='reminder_no')]
    ])

def get_language_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇨🇳 中文", callback_data='lang_zh'),
         InlineKeyboardButton("🇬🇧 ENG", callback_data='lang_en')]
    ])

# Time parsing function
def parse_reminder_time(time_str, language):
    try:
        # Try HH:MM format
        if ':' in time_str:
            hours, minutes = map(int, time_str.split(':'))
            now = datetime.now()
            reminder_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            if reminder_time < now:
                reminder_time += timedelta(days=1)
            return reminder_time
        
        # Try "in X hours" format
        elif language == 'en' and 'hour' in time_str.lower():
            hours = int(''.join(filter(str.isdigit, time_str)))
            return datetime.now() + timedelta(hours=hours)
        
        elif language == 'zh' and ('小時' in time_str or '小时' in time_str):
            hours = int(''.join(filter(str.isdigit, time_str)))
            return datetime.now() + timedelta(hours=hours)
            
    except (ValueError, AttributeError):
        pass
    return None

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    
    await update.message.reply_text(
        text['welcome'],
        reply_markup=get_main_keyboard(language)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    message_text = update.message.text

    if message_text == text['query_all']:
        await query_all_todos(update, context)
    elif message_text == text['query_category']:
        await choose_category(update, context, 'query')
    elif message_text == text['add_todo']:
        await choose_category(update, context, 'add')
    elif message_text == text['change_language']:
        await change_language(update, context)
    else:
        # Handle reminder time input
        if 'waiting_reminder_time' in context.user_data:
            reminder_time = parse_reminder_time(message_text, language)
            if reminder_time:
                category = context.user_data['waiting_category']
                task = context.user_data['waiting_task']
                
                todo_id = add_todo_to_db(user_id, category, task, reminder_time)
                
                # Schedule reminder
                await schedule_reminder(user_id, task, reminder_time, todo_id, context)
                
                await update.message.reply_text(
                    text['reminder_set'].format(reminder_time.strftime('%Y-%m-%d %H:%M')),
                    reply_markup=get_main_keyboard(language)
                )
                del context.user_data['waiting_reminder_time']
                del context.user_data['waiting_category']
                del context.user_data['waiting_task']
            else:
                await update.message.reply_text(text['invalid_time'])
        
        # Handle task input
        elif 'waiting_task' in context.user_data:
            context.user_data['waiting_task'] = message_text
            await update.message.reply_text(
                text['need_reminder'],
                reply_markup=get_reminder_keyboard(language)
            )

async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    data = query.data

    if data.startswith('lang_'):
        new_language = data.split('_')[1]
        set_user_language(user_id, new_language)
        await query.edit_message_text(f"✅ Language changed to {new_language.upper()}")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=TEXTS[new_language]['welcome'],
            reply_markup=get_main_keyboard(new_language)
        )

    elif data.startswith('category_'):
        category = data.split('_')[1]
        if 'operation_type' in context.user_data:
            operation_type = context.user_data['operation_type']
            if operation_type == 'query':
                await show_todos_by_category(query, context, category)
            elif operation_type == 'add':
                context.user_data['waiting_category'] = category
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=text['enter_task']
                )
            del context.user_data['operation_type']

    elif data.startswith('reminder_'):
        if data == 'reminder_yes':
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text['enter_reminder_time']
            )
            context.user_data['waiting_reminder_time'] = True
        else:
            category = context.user_data['waiting_category']
            task = context.user_data['waiting_task']
            add_todo_to_db(user_id, category, task)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text['task_added'],
                reply_markup=get_main_keyboard(language)
            )
            del context.user_data['waiting_category']
            del context.user_data['waiting_task']

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE, operation_type):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    
    context.user_data['operation_type'] = operation_type
    await update.message.reply_text(
        text['choose_category'],
        reply_markup=get_category_keyboard(language)
    )

async def query_all_todos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    
    todos = get_todos(user_id)
    if not todos:
        await update.message.reply_text(text['no_tasks'])
        return
    
    message = text['all_tasks'] + '\n\n'
    for i, (category, task, reminder_time) in enumerate(todos, 1):
        category_name = CATEGORIES[category][language]
        reminder_text = f" ⏰ {reminder_time}" if reminder_time else ""
        message += f"{i}. {category_name}: {task}{reminder_text}\n"
    
    await update.message.reply_text(message)

async def show_todos_by_category(query, context: ContextTypes.DEFAULT_TYPE, category):
    user_id = query.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    
    todos = get_todos(user_id, category)
    if not todos:
        await query.edit_message_text(text['no_tasks'])
        return
    
    category_name = CATEGORIES[category][language]
    message = text['tasks_in_category'].format(category_name) + '\n\n'
    for i, (_, task, reminder_time) in enumerate(todos, 1):
        reminder_text = f" ⏰ {reminder_time}" if reminder_time else ""
        message += f"{i}. {task}{reminder_text}\n"
    
    await query.edit_message_text(message)

async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 請選擇語言 / Please choose language:",
        reply_markup=get_language_keyboard()
    )

async def schedule_reminder(user_id, task, reminder_time, todo_id, context):
    async def send_reminder():
        try:
            language = get_user_language(user_id)
            text = TEXTS[language]
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏰ 提醒: {task}\n{text['category_' + context.user_data.get('waiting_category', '')]}"
            )
        except Exception as e:
            logger.error(f"Failed to send reminder: {e}")

    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(run_date=reminder_time),
        id=f"reminder_{todo_id}"
    )

# 健康检查服务器类
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok", "service": "telegram-todo-bot"}')
        else:
            self.send_response(404)
            self.end_headers()

def run_health_server():
    """运行健康检查服务器"""
    server = HTTPServer(('0.0.0.0', 10000), HealthCheckHandler)
    logger.info("Health check server started on port 10000")
    server.serve_forever()

def main():
    """Start the bot."""
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        return
    
    # Initialize database
    init_db()
    
    # Start scheduler
    scheduler.start()
    
    # 启动健康检查服务器（在单独线程中）
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Create the Application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_query))
    
    logger.info("Starting bot with polling mode...")
    
    # 使用Polling模式（Render免费版兼容）
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            close_loop=False
        )
    except Exception as e:
        logger.error(f"Polling error: {e}")
DATABASE_URL = os.getenv('DATABASE_URL')
def get_db_connection():
    """獲取PostgreSQL數據庫連接"""
    conn = psycopg2.connect(DATABASE_URL)
    return conn
def init_db():
    """初始化數據庫表結構"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # 創建users表
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id BIGINT PRIMARY KEY, 
                  language TEXT DEFAULT 'zh', 
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # 創建todos表
    c.execute('''CREATE TABLE IF NOT EXISTS todos
                 (id SERIAL PRIMARY KEY, 
                  user_id BIGINT, 
                  category TEXT,
                  task TEXT, 
                  reminder_time TIMESTAMP NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(user_id) REFERENCES users(user_id))''')
    
    conn.commit()
    conn.close()
def get_user_language(user_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT language FROM users WHERE user_id = %s", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 'zh'
def set_user_language(user_id, language):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id, language) 
        VALUES (%s, %s)
        ON CONFLICT (user_id) 
        DO UPDATE SET language = EXCLUDED.language
    """, (user_id, language))
    conn.commit()
    conn.close()
def add_todo_to_db(user_id, category, task, reminder_time=None):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO todos (user_id, category, task, reminder_time) 
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """, (user_id, category, task, reminder_time))
    todo_id = c.fetchone()[0]
    conn.commit()
    conn.close()
    return todo_id
def get_db_connection():
    """獲取PostgreSQL數據庫連接"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except psycopg2.Error as e:
        logger.error(f"Database connection error: {e}")
        raise
def get_todos(user_id, category=None):
    conn = get_db_connection()
    c = conn.cursor()
    if category:
        c.execute("""
            SELECT category, task, reminder_time 
            FROM todos 
            WHERE user_id = %s AND category = %s 
            ORDER BY created_at
        """, (user_id, category))
    else:
        c.execute("""
            SELECT category, task, reminder_time 
            FROM todos 
            WHERE user_id = %s 
            ORDER BY created_at
        """, (user_id,))
    todos = c.fetchall()
    conn.close()
    return todos

if __name__ == '__main__':
    main()
