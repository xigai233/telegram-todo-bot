import os
import logging
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
import psycopg2.pool
import socket

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 环境变量
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
PORT = int(os.getenv('PORT', 8443))  # Render 设置的端口，默认 8443 用于 webhook

# 全局连接池和调度器
db_pool = None
scheduler = AsyncIOScheduler()

# Language texts (unchanged)
TEXTS = {
    'zh': {
        'welcome': '👋 歡迎使用待辦事項機器人！\n使用 /help 查看幫助',
        'choose_language': '🌐 請選擇語言：',
        'main_menu': '🏠 主選單 - 請選擇操作：',
        'query_all': '📋 所有待辦事項',
        'query_category': '🔍 分類查詢',
        'add_todo': '📝 新增待辦',
        'delete_todo': '🗑️ 刪除待辦',
        'change_language': '🌐 切換語言',
        'help': '❓ 幫助',
        'choose_category': '📂 請選擇類別：',
        'enter_task': '✏️ 請輸入待辦事項內容：',
        'need_reminder': '⏰ 需要設置提醒嗎？',
        'enter_reminder_time': '🕒 請輸入提醒時間（格式：HH:MM 或 幾小時後）：',
        'task_added': '✅ 已成功添加待辦事項！',
        'no_tasks': '📭 目前沒有待辦事項',
        'tasks_in_category': '📋 {}類別的待辦事項：',
        'all_tasks': '📋 所有待辦事項：',
        'reminder_set': '⏰ 已設置提醒於 {}',
        'invalid_time': '❌ 時間格式錯誤，請使用 HH:MM 格式或 "X小時後"',
        'category_game': '🎮 遊戲',
        'category_movie': '📺 影視',
        'category_action': '⭐ 行動',
        'choose_todo_delete': '🗑️ 請選擇要刪除的待辦事項：',
        'task_deleted': '✅ 已刪除待辦事項',
        'help_text': '📖 幫助：\n- 新增待辦：選擇類別 > 輸入內容 > 選擇是否提醒\n- 查詢：查看所有或按類別\n- 刪除：選擇要刪除的項目\n- 語言：切換中英'
    },
    'en': {
        'welcome': '👋 Welcome to Todo Bot!\nUse /help for help',
        'choose_language': '🌐 Please choose language:',
        'main_menu': '🏠 Main Menu - Please choose operation:',
        'query_all': '📋 All Todos',
        'query_category': '🔍 Query by Category',
        'add_todo': '📝 Add Todo',
        'delete_todo': '🗑️ Delete Todo',
        'change_language': '🌐 Change Language',
        'help': '❓ Help',
        'choose_category': '📂 Please choose category:',
        'enter_task': '✏️ Please enter todo content:',
        'need_reminder': '⏰ Do you need a reminder?',
        'enter_reminder_time': '🕒 Please enter reminder time (format: HH:MM or in X hours):',
        'task_added': '✅ Todo added successfully!',
        'no_tasks': '📭 No tasks at the moment',
        'tasks_in_category': '📋 Todos in {} category:',
        'all_tasks': '📋 All todos:',
        'reminder_set': '⏰ Reminder set for {}',
        'invalid_time': '❌ Invalid time format, please use HH:MM or "in X hours"',
        'category_game': '🎮 Games',
        'category_movie': '📺 Movies',
        'category_action': '⭐ Actions',
        'choose_todo_delete': '🗑️ Please select todo to delete:',
        'task_deleted': '✅ Todo deleted successfully',
        'help_text': '📖 Help:\n- Add Todo: Choose category > Enter content > Set reminder if needed\n- Query: View all or by category\n- Delete: Select item to delete\n- Language: Switch between EN/ZH'
    }
}

# Categories (unchanged)
CATEGORIES = {
    'game': {'zh': '🎮 遊戲', 'en': '🎮 Games'},
    'movie': {'zh': '📺 影視', 'en': '📺 Movies'},
    'action': {'zh': '⭐ 行動', 'en': '⭐ Actions'}
}

# 初始化数据库连接池 (unchanged)
def init_db_pool():
    global db_pool
    try:
        db_pool = psycopg2.pool.SimpleConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=DATABASE_URL,
            sslmode='require'
        )
        logger.info("Database connection pool initialized")
    except Exception as e:
        logger.critical(f"Database pool initialization failed: {e}")
        raise

def get_db_connection():
    global db_pool
    if db_pool is None:
        raise Exception("Database connection pool is not initialized")
    try:
        return db_pool.getconn()
    except Exception as e:
        logger.error(f"Error getting connection from pool: {e}")
        raise

def put_db_connection(conn):
    if conn:
        db_pool.putconn(conn)

def close_db_pool():
    global db_pool
    if db_pool:
        db_pool.closeall()
        logger.info("Database connection pool closed")

# Database functions (unchanged, with added logging for debug)
def init_db():
    """初始化數據庫表結構"""
    conn = None
    try:
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
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}")
        raise
    finally:
        put_db_connection(conn)

def get_user_language(user_id):
    """獲取用戶語言設置"""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT language FROM users WHERE user_id = %s", (user_id,))
        result = c.fetchone()
        return result[0] if result else 'zh'
    except Exception as e:
        logger.error(f"Error getting user language: {e}")
        return 'zh'
    finally:
        put_db_connection(conn)

def set_user_language(user_id, language):
    """設置用戶語言"""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id, language) 
            VALUES (%s, %s)
            ON CONFLICT (user_id) 
            DO UPDATE SET language = EXCLUDED.language
        """, (user_id, language))
        conn.commit()
        logger.debug(f"Set language for user {user_id} to {language}")
    except Exception as e:
        logger.error(f"Error setting user language: {e}")
        raise
    finally:
        put_db_connection(conn)

def add_todo_to_db(user_id, category, task, reminder_time=None):
    """添加待辦事項到數據庫"""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # 確保用戶存在
        c.execute("""
            INSERT INTO users (user_id) 
            VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id,))
        # 插入待辦事項
        c.execute("""
            INSERT INTO todos (user_id, category, task, reminder_time) 
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (user_id, category, task, reminder_time))
        todo_id = c.fetchone()[0]
        conn.commit()
        logger.debug(f"Added todo {todo_id} for user {user_id}: {task}")
        return todo_id
    except Exception as e:
        logger.error(f"Error adding todo: {e}")
        raise
    finally:
        put_db_connection(conn)

def get_todos(user_id, category=None):
    """獲取待辦事項列表"""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        if category:
            c.execute("""
                SELECT id, category, task, reminder_time 
                FROM todos 
                WHERE user_id = %s AND category = %s 
                ORDER BY created_at
            """, (user_id, category))
        else:
            c.execute("""
                SELECT id, category, task, reminder_time 
                FROM todos 
                WHERE user_id = %s 
                ORDER BY created_at
            """, (user_id,))
        todos = c.fetchall()
        logger.debug(f"Retrieved {len(todos)} todos for user {user_id}")
        return todos
    except Exception as e:
        logger.error(f"Error getting todos: {e}")
        return []
    finally:
        put_db_connection(conn)

def delete_todo(user_id, todo_id):
    """刪除待辦事項"""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            DELETE FROM todos 
            WHERE user_id = %s AND id = %s
        """, (user_id, todo_id))
        conn.commit()
        deleted = c.rowcount > 0
        logger.debug(f"Deleted todo {todo_id} for user {user_id}: {deleted}")
        return deleted
    except Exception as e:
        logger.error(f"Error deleting todo: {e}")
        return False
    finally:
        put_db_connection(conn)

# Keyboard functions (unchanged)
def get_main_keyboard(language):
    text = TEXTS[language]
    return ReplyKeyboardMarkup([
        [text['query_all'], text['query_category']],
        [text['add_todo'], text['delete_todo']],
        [text['change_language'], text['help']]
    ], resize_keyboard=True, one_time_keyboard=False)

def get_category_keyboard(language, operation_type):
    keyboard = []
    for category_id, category_names in CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(category_names[language], callback_data=f'{operation_type}_category_{category_id}')])
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

def get_delete_keyboard(language, todos):
    keyboard = []
    for todo_id, _, task, _ in todos:
        keyboard.append([InlineKeyboardButton(f"{task[:20]}...", callback_data=f'delete_{todo_id}')])
    return InlineKeyboardMarkup(keyboard)

# Time parsing function (unchanged)
def parse_reminder_time(time_str, language):
    try:
        time_str = time_str.lower().strip()
        # Try HH:MM format
        if ':' in time_str:
            hours, minutes = map(int, time_str.split(':'))
            now = datetime.now()
            reminder_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            if reminder_time < now:
                reminder_time += timedelta(days=1)
            return reminder_time
        
        # Try "in X hours" format
        if language == 'en':
            if 'hour' in time_str or 'hours' in time_str:
                hours = int(''.join(filter(str.isdigit, time_str)))
                return datetime.now() + timedelta(hours=hours)
        elif language == 'zh':
            if '小時' in time_str or '小时' in time_str or '後' in time_str or '后' in time_str:
                hours = int(''.join(filter(str.isdigit, time_str)))
                return datetime.now() + timedelta(hours=hours)
            
    except (ValueError, AttributeError):
        pass
    return None

# Handlers (unchanged except for error handling)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    
    await update.message.reply_text(
        text['welcome'],
        reply_markup=get_main_keyboard(language)
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    
    await update.message.reply_text(
        text['help_text'],
        reply_markup=get_main_keyboard(language)
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    context.user_data.clear()
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
    elif message_text == text['delete_todo']:
        await choose_delete(update, context)
    elif message_text == text['change_language']:
        await change_language(update, context)
    elif message_text == text['help']:
        await help_command(update, context)
    else:
        # Handle task input
        if 'waiting_task' in context.user_data:
            context.user_data['waiting_task'] = message_text
            await update.message.reply_text(
                text['need_reminder'],
                reply_markup=get_reminder_keyboard(language)
            )
            # Removed erroneous del here - state is cleared in callback or after time input
        # Handle reminder time input
        elif 'waiting_reminder_time' in context.user_data:
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
                context.user_data.clear()
            else:
                await update.message.reply_text(
                    text['invalid_time'] + '\n' + text['enter_reminder_time']
                )
                # Keep waiting for valid input

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

    elif data.startswith('add_category_'):
        category = data.split('_')[2]
        context.user_data['waiting_category'] = category
        context.user_data['waiting_task'] = True
        await query.edit_message_text(text['enter_task'])

    elif data.startswith('query_category_'):
        category = data.split('_')[2]
        await show_todos_by_category(query, context, category)

    elif data.startswith('reminder_'):
        if 'waiting_task' not in context.user_data or 'waiting_category' not in context.user_data:
            await query.edit_message_text("❌ 操作已過期，請重新開始")
            return

        if data == 'reminder_yes':
            await query.edit_message_text(text['enter_reminder_time'])
            context.user_data['waiting_reminder_time'] = True
        else:
            category = context.user_data['waiting_category']
            task = context.user_data['waiting_task']
            add_todo_to_db(user_id, category, task)
            await query.edit_message_text(text['task_added'])
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=text['main_menu'],
                reply_markup=get_main_keyboard(language)
            )
            context.user_data.clear()

    elif data.startswith('delete_'):
        todo_id = int(data.split('_')[1])
        if delete_todo(user_id, todo_id):
            await query.edit_message_text(text['task_deleted'])
        else:
            await query.edit_message_text("❌ 刪除失敗")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            reply_markup=get_main_keyboard(language)
        )

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE, operation_type):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    
    await update.message.reply_text(
        text['choose_category'],
        reply_markup=get_category_keyboard(language, operation_type)
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
    for i, (_, category, task, reminder_time) in enumerate(todos, 1):
        category_name = CATEGORIES[category][language]
        reminder_text = f" ⏰ {reminder_time.strftime('%Y-%m-%d %H:%M')}" if reminder_time else ""
        message += f"{i}. {category_name}: {task}{reminder_text}\n"
    
    await update.message.reply_text(message, reply_markup=get_main_keyboard(language))

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
    for i, (_, _, task, reminder_time) in enumerate(todos, 1):
        reminder_text = f" ⏰ {reminder_time.strftime('%Y-%m-%d %H:%M')}" if reminder_time else ""
        message += f"{i}. {task}{reminder_text}\n"
    
    await query.edit_message_text(message)

async def choose_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    language = get_user_language(user_id)
    text = TEXTS[language]
    
    todos = get_todos(user_id)
    if not todos:
        await update.message.reply_text(text['no_tasks'])
        return
    
    await update.message.reply_text(
        text['choose_todo_delete'],
        reply_markup=get_delete_keyboard(language, todos)
    )

async def change_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 請選擇語言 / Please choose language:",
        reply_markup=get_language_keyboard()
    )

async def schedule_reminder(user_id, task, reminder_time, todo_id, context):
    async def send_reminder():
        try:
            language = get_user_language(user_id)
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⏰ 提醒: {task}"
            )
        except Exception as e:
            logger.error(f"Failed to send reminder for todo_id {todo_id}: {e}")

    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(run_date=reminder_time),
        id=f"reminder_{todo_id}_{user_id}"
    )

# 健康检查服务器类 (unchanged)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        logger.info(f"Received health check request: {self.path}")
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = json.dumps({"status": "ok", "service": "telegram-todo-bot"})
            self.wfile.write(response.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            logger.warning(f"Invalid health check path: {self.path}")

def is_port_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('0.0.0.0', port)) != 0

def run_health_server():
    """运行健康检查服务器"""
    port = 10000
    if not is_port_available(port):
        logger.error(f"Port {port} is already in use")
        return
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    logger.info(f"Health check server started on port {port}")
    server.serve_forever()

def check_env_vars():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")

async def main():
    """Start the bot with webhook."""
    try:
        check_env_vars()
        init_db_pool()
        init_db()
        logger.info("Database initialized successfully")
        scheduler.start()
        logger.info("Scheduler started successfully")
        health_thread = threading.Thread(target=run_health_server, daemon=True)
        health_thread.start()
        logger.info("Health check server started")
        
        # Create the Application
        application = Application.builder().token(TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("cancel", cancel))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(callback_query))
        
        # Set webhook (Render provides RENDER_EXTERNAL_HOSTNAME)
        external_hostname = os.getenv('RENDER_EXTERNAL_HOSTNAME')
        if not external_hostname:
            raise ValueError("RENDER_EXTERNAL_HOSTNAME not set - required for webhook")
        
        webhook_url = f"https://{external_hostname}/{TOKEN}"
        await application.bot.set_webhook(webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
        
        # Start webhook server
        await application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TOKEN,
            webhook_url=webhook_url
        )
        
    except telegram.error.Conflict as e:
        logger.critical(f"Telegram conflict error: {e}. Ensure single instance and no polling conflicts.")
        # Optional retry logic or shutdown
    except Exception as e:
        logger.critical(f"Bot startup failed: {e}")
    finally:
        scheduler.shutdown()
        close_db_pool()
        logger.info("Bot stopped")

if __name__ == '__main__':
    asyncio.run(main())