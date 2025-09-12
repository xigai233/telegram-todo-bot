import os
import logging
import asyncio
import random
import hashlib
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import psycopg2
import psycopg2.pool

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 环境变量
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')

# 全局连接池
db_pool = None

# 只保留繁体中文文本
TEXTS = {
    'welcome': '👋 歡迎使用待辦事項機器人！\n使用 /help 查看幫助',
    'main_menu': '🏠 主選單 - 請選擇操作：',
    'query_all': '📋 所有待辦事項',
    'query_category': '🔍 分類查詢',
    'add_todo': '📝 新增待辦',
    'delete_todo': '🗑️ 刪除待辦',
    'help': '❓ 幫助',
    'choose_category': '📂 請選擇類別：',
    'enter_task': '✏️ 請輸入待辦事項內容：',
    'need_reminder': '⏰ 需要設置提醒嗎？',
    'enter_reminder_time': '🕒 請輸入提醒時間（格式：HH:MM）：',
    'task_added': '✅ 已成功添加待辦事項！',
    'no_tasks': '📭 目前沒有待辦事項',
    'tasks_in_category': '📋 {}類別的待辦事項：',
    'all_tasks': '📋 所有待辦事項：',
    'invalid_time': '❌ 時間格式錯誤，請使用 HH:MM 格式',
    'category_game': '🎮 遊戲',
    'category_movie': '📺 影視',
    'category_action': '⭐ 行動',
    'choose_todo_delete': '🗑️ 請選擇要刪除的待辦事項：',
    'task_deleted': '✅ 已刪除待辦事項',
    'help_text': '📖 幫助：\n- 新增待辦：選擇類別 > 輸入內容\n- 查詢：查看所有或按類別\n- 刪除：選擇要刪除的項目',
    'create_room': '🏠 創建房間',
    'join_room': '🔑 加入房間',
    'enter_room_name': '📛 請輸入房間名稱：',
    'enter_room_password': '🔒 請設置房間密碼：',
    'enter_room_code': '🔢 請輸入房間號碼：',
    'enter_join_password': '🔐 請輸入房間密碼：',
    'room_created': '✅ 房間創建成功！房間號：{}\n請分享給其他成員',
    'join_success': '✅ 成功加入房間：{}',
    'join_failed': '❌ 加入失敗：{}',
    'not_in_room': '❌ 請先加入房間',
    'room_notification': '📢 房間通知：{}'
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

# 房间管理功能
def generate_room_code():
    """生成4位数房间号"""
    return str(random.randint(1000, 9999))

def hash_password(password):
    """密码哈希处理"""
    return hashlib.sha256(password.encode()).hexdigest()

def create_room(room_name, password, owner_id):
    """创建房间"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        room_code = generate_room_code()
    
        # 确保房间号不重复
        while True:
            c.execute("SELECT room_code FROM rooms WHERE room_code = %s", (room_code,))
            if not c.fetchone():
                break
            room_code = generate_room_code()
    
        hashed_password = hash_password(password)
        c.execute("""
            INSERT INTO rooms (room_code, room_name, password, owner_id)
            VALUES (%s, %s, %s, %s)
        """, (room_code, room_name, hashed_password, owner_id))
    
        # 自动将创建者加入房间
        c.execute("""
            INSERT INTO room_members (room_code, user_id)
            VALUES (%s, %s)
        """, (room_code, owner_id))
    
        conn.commit()
        return room_code
    except Exception as e:
        logger.error(f"Error creating room: {e}")
        raise
    finally:
        put_db_connection(conn)

def join_room(room_code, password, user_id):
    """加入房间"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
    
        # 验证房间和密码
        c.execute("SELECT password, room_name FROM rooms WHERE room_code = %s", (room_code,))
        result = c.fetchone()
        if not result:
            return False, "房間不存在"
    
        hashed_password, room_name = result
        if hash_password(password) != hashed_password:
            return False, "密碼錯誤"
    
        # 加入房间
        try:
            c.execute("""
                INSERT INTO room_members (room_code, user_id)
                VALUES (%s, %s)
                ON CONFLICT (room_code, user_id) DO NOTHING
            """, (room_code, user_id))
            conn.commit()
            return True, room_name
        except Exception as e:
            logger.error(f"Error joining room: {e}")
            return False, "加入失敗"
        
    except Exception as e:
        logger.error(f"Error in join_room: {e}")
        return False, "系統錯誤"
    finally:
        put_db_connection(conn)

async def notify_room_members(room_code, message, context: ContextTypes.DEFAULT_TYPE):
    """向房间所有成员发送通知"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id FROM room_members WHERE room_code = %s", (room_code,))
        members = c.fetchall()
    
        for (user_id,) in members:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=TEXTS['room_notification'].format(message)
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Error notifying room members: {e}")
    finally:
        put_db_connection(conn)

def migrate_database():
    """自動遷移數據庫結構"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
    
        # 1. 首先創建rooms表（如果不存在）
        c.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                room_code TEXT PRIMARY KEY,
                room_name TEXT,
                password TEXT,
                owner_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    
        # 2. 創建room_members表（如果不存在）
        c.execute('''
            CREATE TABLE IF NOT EXISTS room_members (
                id SERIAL PRIMARY KEY,
                room_code TEXT,
                user_id BIGINT,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(room_code) REFERENCES rooms(room_code),
                UNIQUE(room_code, user_id)
            )
        ''')
    
        # 3. 檢查todos表是否有room_code列
        c.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'todos' AND column_name = 'room_code'
        """)
        has_room_code = c.fetchone()
    
        if not has_room_code:
            logger.info("檢測到舊數據庫結構，開始遷移...")
        
            # 4. 檢查舊表的結構
            c.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'todos' 
                ORDER BY ordinal_position
            """)
            old_columns = c.fetchall()
            logger.info(f"舊表結構: {old_columns}")
        
            # 5. 創建新表結構（包含room_code）
            c.execute('''
                CREATE TABLE todos_new (
                    id SERIAL PRIMARY KEY, 
                    room_code TEXT DEFAULT 'default_room',
                    user_id BIGINT, 
                    category TEXT,
                    task TEXT, 
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(room_code) REFERENCES rooms(room_code),
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                )
            ''')
        
            # 6. 創建默認房間用於遷移數據
            c.execute("""
                INSERT INTO rooms (room_code, room_name, password, owner_id)
                VALUES ('default_room', '默認房間', %s, 0)
                ON CONFLICT (room_code) DO NOTHING
            """, (hash_password('default'),))
        
            # 7. 遷移數據 - 明確指定列名
            c.execute("""
                INSERT INTO todos_new (user_id, category, task, created_at)
                SELECT user_id, category, task, created_at FROM todos
            """)
        
            # 8. 刪除舊表並重命名新表
            c.execute("DROP TABLE todos")
            c.execute("ALTER TABLE todos_new RENAME TO todos")
        
            logger.info("數據庫遷移完成")
        else:
            logger.info("數據庫結構已是最新")
        
        conn.commit()
    
    except Exception as e:
        logger.error(f"數據庫遷移失敗: {e}")
        conn.rollback()
        raise
    finally:
        put_db_connection(conn)

# Database functions
def init_db():
    """初始化數據庫"""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
    
        # 創建用戶表（必須最先創建）
        c.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    
        conn.commit()
        logger.info("基礎用戶表初始化成功")
    
        # 執行自動遷移
        migrate_database()
    
    except Exception as e:
        logger.critical(f"數據庫初始化失敗: {e}")
        raise
    finally:
        put_db_connection(conn)

def add_todo_to_db(room_code, user_id, category, task, context: ContextTypes.DEFAULT_TYPE = None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
    
        # 確保用戶存在
        c.execute("""
            INSERT INTO users (user_id) 
            VALUES (%s)
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id,))
    
        # 確保房間存在（如果是新系統，可能還沒有房間）
        c.execute("SELECT 1 FROM rooms WHERE room_code = %s", (room_code,))
        room_exists = c.fetchone()
    
        if not room_exists:
            # 創建一個默認房間（用於遷移期間的兼容性）
            c.execute("""
                INSERT INTO rooms (room_code, room_name, password, owner_id)
                VALUES (%s, '臨時房間', %s, %s)
                ON CONFLICT (room_code) DO NOTHING
            """, (room_code, hash_password('temp'), user_id))
        
            # 將用戶加入房間
            c.execute("""
                INSERT INTO room_members (room_code, user_id)
                VALUES (%s, %s)
                ON CONFLICT (room_code, user_id) DO NOTHING
            """, (room_code, user_id))
    
        # 添加待辦
        c.execute("""
            INSERT INTO todos (room_code, user_id, category, task) 
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (room_code, user_id, category, task))
    
        todo_id = c.fetchone()[0]
        conn.commit()
    
        # 發送通知
        if context:
            asyncio.create_task(notify_room_members(
                room_code, 
                f"📝 新待辦事項添加：\n{task}\n類別：{category}",
                context
            ))
    
        return todo_id
    
    except Exception as e:
        logger.error(f"添加待辦失敗: {e}")
        conn.rollback()
        raise
    finally:
        put_db_connection(conn)
def get_todos(room_code, category=None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
      
        # 確保房間存在
        c.execute("SELECT 1 FROM rooms WHERE room_code = %s", (room_code,))
        if not c.fetchone():
            return []  # 房間不存在，返回空列表
          
        if category:
            c.execute("""
                SELECT id, user_id, category, task
                FROM todos 
                WHERE room_code = %s AND category = %s 
                ORDER BY created_at
            """, (room_code, category))
        else:
            c.execute("""
                SELECT id, user_id, category, task
                FROM todos 
                WHERE room_code = %s 
                ORDER BY created_at
            """, (room_code,))
          
        todos = c.fetchall()
        return todos
      
    except Exception as e:
        logger.error(f"查詢待辦失敗: {e}")
        return []
    finally:
        put_db_connection(conn)
def delete_todo(room_code, todo_id, context: ContextTypes.DEFAULT_TYPE = None):
    conn = get_db_connection()
    try:
        c = conn.cursor()
      
        # 先获取待办信息用于通知
        c.execute("SELECT task FROM todos WHERE id = %s AND room_code = %s", (todo_id, room_code))
        result = c.fetchone()
      
        if not result:
            return False
      
        task = result[0]
      
        # 删除待办
        c.execute("""
            DELETE FROM todos 
            WHERE id = %s AND room_code = %s
        """, (todo_id, room_code))
      
        conn.commit()
        success = c.rowcount > 0
      
        # 发送通知（如果删除成功且提供了context）
        if success and context:
            asyncio.create_task(notify_room_members(
                room_code, 
                f"🗑️ 待辦事項已刪除：\n{task}",
                context
            ))
      
        return success
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
        [TEXTS['create_room'], TEXTS['join_room']],
        [TEXTS['help']]
    ], resize_keyboard=True, one_time_keyboard=False)
def get_category_keyboard(operation_type):
    keyboard = []
    for category_id, category_name in CATEGORIES.items():
        keyboard.append([InlineKeyboardButton(category_name, callback_data=f'{operation_type}_category_{category_id}')])
    return InlineKeyboardMarkup(keyboard)
def get_delete_keyboard(todos):
    keyboard = []
    for todo_id, _, _, task in todos:
        keyboard.append([InlineKeyboardButton(f"{task[:20]}...", callback_data=f'delete_{todo_id}')])
    return InlineKeyboardMarkup(keyboard)
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
    # 房间管理功能
    if message_text == TEXTS['create_room']:
        context.user_data['waiting_room_name'] = True
        await update.message.reply_text(TEXTS['enter_room_name'])
        return
  
    elif message_text == TEXTS['join_room']:
        context.user_data['waiting_room_code'] = True
        await update.message.reply_text(TEXTS['enter_room_code'])
        return
  
    elif 'waiting_room_name' in context.user_data:
        context.user_data['room_name'] = message_text
        context.user_data['waiting_room_password'] = True
        context.user_data.pop('waiting_room_name')
        await update.message.reply_text(TEXTS['enter_room_password'])
        return
  
    elif 'waiting_room_password' in context.user_data:
        room_name = context.user_data['room_name']
        password = message_text
        room_code = create_room(room_name, password, user_id)
        context.user_data.clear()
        context.user_data['current_room'] = room_code
        await update.message.reply_text(
            TEXTS['room_created'].format(room_code),
            reply_markup=get_main_keyboard()
        )
        return
    
    elif 'waiting_room_code' in context.user_data:
        context.user_data['room_code'] = message_text
        context.user_data['waiting_join_password'] = True
        context.user_data.pop('waiting_room_code')
        await update.message.reply_text(TEXTS['enter_join_password'])
        return
    
    elif 'waiting_join_password' in context.user_data:
        room_code = context.user_data['room_code']
        password = message_text
        success, message = join_room(room_code, password, user_id)
        context.user_data.clear()
        
        if success:
            context.user_data['current_room'] = room_code
            await update.message.reply_text(
                TEXTS['join_success'].format(message),
                reply_markup=get_main_keyboard()
            )
        else:
            await update.message.reply_text(
                TEXTS['join_failed'].format(message),
                reply_markup=get_main_keyboard()
            )
        return
    # 原有功能（需要检查是否在房间中）
    if 'current_room' not in context.user_data:
        if message_text in [TEXTS['query_all'], TEXTS['query_category'], TEXTS['add_todo'], TEXTS['delete_todo']]:
            await update.message.reply_text(TEXTS['not_in_room'])
            return
    
    room_code = context.user_data.get('current_room')
    
    if message_text == TEXTS['query_all']:
        await query_all_todos(update, context, room_code)
    elif message_text == TEXTS['query_category']:
        await choose_category(update, context, 'query')
    elif message_text == TEXTS['add_todo']:
        await choose_category(update, context, 'add')
    elif message_text == TEXTS['delete_todo']:
        await choose_delete(update, context, room_code)
    elif message_text == TEXTS['help']:
        await help_command(update, context)
    else:
        if 'waiting_task' in context.user_data:
            category = context.user_data['waiting_category']
            task = message_text
            try:
                add_todo_to_db(room_code, user_id, category, task, context)
                await update.message.reply_text(
                    TEXTS['task_added'],
                    reply_markup=get_main_keyboard()
                )
            except Exception as e:
                logger.error(f"添加待辦失敗: {e}")
                await update.message.reply_text(
                    "❌ 添加失敗，請稍後重試",
                    reply_markup=get_main_keyboard()
                )
            finally:
                context.user_data.clear()
async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if 'current_room' not in context.user_data:
        await query.edit_message_text(TEXTS['not_in_room'])
        return
    
    room_code = context.user_data['current_room']
    data = query.data
    if data.startswith('add_category_'):
        category = data.split('_')[2]
        context.user_data['waiting_category'] = category
        context.user_data['waiting_task'] = True
        await query.edit_message_text(TEXTS['enter_task'])
    elif data.startswith('query_category_'):
        category = data.split('_')[2]
        await show_todos_by_category(query, context, room_code, category)
    elif data.startswith('delete_'):
        todo_id = int(data.split('_')[1])
        if delete_todo(room_code, todo_id, context):
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
async def query_all_todos(update: Update, context: ContextTypes.DEFAULT_TYPE, room_code):
    todos = get_todos(room_code)
    if not todos:
        await update.message.reply_text(TEXTS['no_tasks'])
        return
    
    message = TEXTS['all_tasks'] + '\n\n'
    for i, (_, user_id, category, task) in enumerate(todos, 1):
        category_name = CATEGORIES[category]
        message += f"{i}. {category_name}: {task}\n"
    
    await update.message.reply_text(message, reply_markup=get_main_keyboard())
async def show_todos_by_category(query, context: ContextTypes.DEFAULT_TYPE, room_code, category):
    todos = get_todos(room_code, category)
    if not todos:
        await query.edit_message_text(TEXTS['no_tasks'])
        return
    
    category_name = CATEGORIES[category]
    message = TEXTS['tasks_in_category'].format(category_name) + '\n\n'
    for i, (_, _, _, task) in enumerate(todos, 1):
        message += f"{i}. {task}\n"
    
    await query.edit_message_text(message)
async def choose_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, room_code):
    todos = get_todos(room_code)
    if not todos:
        await update.message.reply_text(TEXTS['no_tasks'])
        return
    
    await update.message.reply_text(
        TEXTS['choose_todo_delete'],
        reply_markup=get_delete_keyboard(todos)
    )
def check_env_vars():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")
def main():
    application = None
    try:
        check_env_vars()
        init_db_pool()
        init_db()
        
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(callback_query))
        
        logger.info("Starting bot with polling mode...")
        
        # 使用同步的 run_polling 方法
        application.run_polling()
            
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
        raise
    finally:
        close_db_pool()
if __name__ == '__main__':
    # 直接调用同步的 main 函数
    main()