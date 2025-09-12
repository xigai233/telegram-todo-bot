import os
import logging
import json
import asyncio
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
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

# 全局连接池和调度器
db_pool = None
scheduler = AsyncIOScheduler()

# 只保留繁体中文文本
TEXTS = {
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
}

# Categories
CATEGORIES = {
    'game': '🎮 遊戲',
    'movie': '📺 影視',
    'action': '⭐ 行動'
}

# 初始化数据库连接池
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

# Database functions
def init_db():
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id BIGINT PRIMARY KEY, 
                      language TEXT DEFAULT 'zh', 
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
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

def add_todo_to_db(user_id, category, task, reminder_time=None):
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (user_id) 
            VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id,))
        c.execute("""
            INSERT INTO todos (user_id, category, task, reminder_time) 
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (user_id, category, task, reminder_time))
        todo_id = c.fetchone()[0]
        conn.commit()
        return todo_id
    except Exception as e:
        logger.error(f"Error adding todo: {e}")
        raise
    finally:
        put_db_connection(conn)

def get_todos(user_id, category=None):
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
        return todos
    except Exception as e:
        logger.error(f"Error getting todos: {e}")
        return []
    finally:
        put_db_connection(conn)

def delete_todo(user_id, todo_id):
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("""
            DELETE FROM todos 
            WHERE user_id = %s AND id = %s
        """, (user_id, todo_id))
        conn.commit()
        return c.rowcount > 0
    except Exception as e:
        logger.error(f"Error deleting todo: {e}")
        return False
    finally:
        put_db_connection(conn)

# Keyboard functions
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [TEXTS['query_all'], TEXTS['query_category']],
        [TEXTS['add_todo'], TEXTS['delete_todo']],
        [TEXTS['change_language'], TEXTS['help']]
    ], resize_keyboard=True, one_time_keyboard=False)

def get_category_keyboard(operation_type):
    keyboard = []
    for category_id, category_name in CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(category_name, callback_data=f'{operation_type}_category_{category_id}')])
    return InlineKeyboardMarkup(keyboard)

def get_reminder_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 是", callback_data='reminder_yes'),
         InlineKeyboardButton("❌ 否", callback_data='reminder_no')]
    ])

def get_delete_keyboard(todos):
    keyboard = []
    for todo_id, _, task, _ in todos:
        keyboard.append([InlineKeyboardButton(f"{task[:20]}...", callback_data=f'delete_{todo_id}')])
    return InlineKeyboardMarkup(keyboard)

# Time parsing function
def parse_reminder_time(time_str):
    try:
        time_str = time_str.lower().strip()
        if ':' in time_str:
            hours, minutes = map(int, time_str.split(':'))
            now = datetime.now()
            reminder_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            if reminder_time < now:
                reminder_time += timedelta(days=1)
            return reminder_time
        if '小時' in time_str or '小时' in time_str or '後' in time_str or '后' in time_str:
            hours = int(''.join(filter(str.isdigit, time_str)))
            return datetime.now() + timedelta(hours=hours)
    except (ValueError, AttributeError):
        pass
    return None

# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        TEXTS['welcome'],
        reply_markup=get_main_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        TEXTS['help_text'],
        reply_markup=get_main_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    message_text = update.message.text

    if message_text == TEXTS['query_all']:
        await query_all_todos(update, context)
    elif message_text == TEXTS['query_category']:
        await choose_category(update, context, 'query')
    elif message_text == TEXTS['add_todo']:
        await choose_category(update, context, 'add')
    elif message_text == TEXTS['delete_todo']:
        await choose_delete(update, context)
    elif message_text == TEXTS['help']:
        await help_command(update, context)
    else:
        if 'waiting_task' in context.user_data:
            context.user_data['waiting_task'] = message_text
            await update.message.reply_text(
                TEXTS['need_reminder'],
                reply_markup=get_reminder_keyboard()
            )
        elif 'waiting_reminder_time' in context.user_data:
            reminder_time = parse_reminder_time(message_text)
            if reminder_time:
                category = context.user_data['waiting_category']
                task = context.user_data['waiting_task']
                todo_id = add_todo_to_db(user_id, category, task, reminder_time)
                await schedule_reminder(user_id, task, reminder_time, todo_id, context)
                await update.message.reply_text(
                    TEXTS['reminder_set'].format(reminder_time.strftime('%Y-%m-%d %H:%M')),
                    reply_markup=get_main_keyboard()
                )
                context.user_data.clear()
            else:
                await update.message.reply_text(
                    TEXTS['invalid_time'] + '\n' + TEXTS['enter_reminder_time']
                )

async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data.startswith('add_category_'):
        category = data.split('_')[2]
        context.user_data['waiting_category'] = category
        context.user_data['waiting_task'] = True
        await query.edit_message_text(TEXTS['enter_task'])
    elif data.startswith('query_category_'):
        category = data.split('_')[2]
        await show_todos_by_category(query, context, category)
    elif data.startswith('reminder_'):
        if 'waiting_task' not in context.user_data or 'waiting_category' not in context.user_data:
            await query.edit_message_text("❌ 操作已過期，請重新開始")
            return
        if data == 'reminder_yes':
            await query.edit_message_text(TEXTS['enter_reminder_time'])
            context.user_data['waiting_reminder_time'] = True
        else:
            category = context.user_data['waiting_category']
            task = context.user_data['waiting_task']
            add_todo_to_db(user_id, category, task)
            await query.edit_message_text(TEXTS['task_added'])
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                reply_markup=get_main_keyboard()
            )
            context.user_data.clear()
    elif data.startswith('delete_'):
        todo_id = int(data.split('_')[1])
        if delete_todo(user_id, todo_id):
            await query.edit_message_text(TEXTS['task_deleted'])
        else:
            await query.edit_message_text("❌ 刪除失敗")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            reply_markup=get_main_keyboard()
        )

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE, operation_type):
    await update.message.reply_text(
        TEXTS['choose_category'],
        reply_markup=get_category_keyboard(operation_type)
    )

async def query_all_todos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    todos = get_todos(user_id)
    if not todos:
        await update.message.reply_text(TEXTS['no_tasks'])
        return
    message = TEXTS['all_tasks'] + '\n\n'
    for i, (_, category, task, reminder_time) in enumerate(todos, 1):
        category_name = CATEGORIES[category]
        reminder_text = f" ⏰ {reminder_time.strftime('%Y-%m-%d %H:%M')}" if reminder_time else ""
        message += f"{i}. {category_name}: {task}{reminder_text}\n"
    await update.message.reply_text(message, reply_markup=get_main_keyboard())

async def show_todos_by_category(query, context: ContextTypes.DEFAULT_TYPE, category):
    user_id = query.from_user.id
    todos = get_todos(user_id, category)
    if not todos:
        await query.edit_message_text(TEXTS['no_tasks'])
        return
    category_name = CATEGORIES[category]
    message = TEXTS['tasks_in_category'].format(category_name) + '\n\n'
    for i, (_, _, task, reminder_time) in enumerate(todos, 1):
        reminder_text = f" ⏰ {reminder_time.strftime('%Y-%m-%d %H:%M')}" if reminder_time else ""
        message += f"{i}. {task}{reminder_text}\n"
    await query.edit_message_text(message)

async def choose_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    todos = get_todos(user_id)
    if not todos:
        await update.message.reply_text(TEXTS['no_tasks'])
        return
    await update.message.reply_text(
        TEXTS['choose_todo_delete'],
        reply_markup=get_delete_keyboard(todos)
    )

async def schedule_reminder(user_id, task, reminder_time, todo_id, context):
    async def send_reminder():
        try:
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

# 健康检查服务器
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ['/', '/health']:
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = json.dumps({"status": "ok", "service": "telegram-todo-bot"})
            self.wfile.write(response.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run_health_server():
    server = HTTPServer(('0.0.0.0', 10000), HealthCheckHandler)
    logger.info("Health check server started on port 10000")
    server.serve_forever()

def check_env_vars():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")

async def main():
    application = None
    try:
        check_env_vars()
        init_db_pool()
        init_db()
        scheduler.start()
        
        # 启动健康检查服务器
        health_thread = threading.Thread(target=run_health_server, daemon=True)
        health_thread.start()
        
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(callback_query))
        
        logger.info("Starting bot with polling mode...")
        
        # 使用正确的轮询模式
        await application.bot.delete_webhook(drop_pending_updates=True)
        await application.run_polling()
            
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
        if application:
            await application.shutdown()
        raise
    finally:
        if scheduler.running:
            scheduler.shutdown()
        close_db_pool()

if __name__ == '__main__':
    # 使用现代的事件循环启动方式
    asyncio.run(main())
