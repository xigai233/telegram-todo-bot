import os
import logging
import random
import hashlib
import threading
import time
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import psycopg2
import psycopg2.pool
import asyncio
import json
import http.server
import socketserver

def run_health_check_server():
    """运行一个极简的健康检查服务器"""
    port = int(os.getenv('PORT', 10000))
    
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path in ['/', '/health', '/ping']:
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'OK')
            else:
                self.send_response(404)
                self.end_headers()
    
    # 使用单线程服务器避免冲突
    with socketserver.TCPServer(("", port), HealthHandler) as httpd:
        logger.info(f"Health check server started on port {port}")
        httpd.serve_forever()

# 配置日志 - 减少噪音
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 降低某些库的日志级别
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def create_flask_app():
    app = Flask(__name__)
    
    @app.route('/')
    def health_check():
        return 'Bot is running'
    
    @app.route('/health')
    def health():
        return 'OK'
    
    return app

def run_web_server():
    """运行Flask服务器来满足Render的端口检测"""
    app = create_flask_app()
    port = int(os.getenv('PORT', 10000))
    logger.info(f"Starting web server on port {port}")
    # 注意：use_reloader=False 很重要，避免在子线程中重新加载
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

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
    'room_options': '🏠 房間選項',
    'create_room': '📝 創建房間',
    'join_room': '🔑 加入房間',
    'leave_room': '🚪 離開房間',
    'enter_room_name': '📛 請輸入房間名稱：',
    'enter_room_password': '🔒 請設置房間密碼：',
    'enter_room_code': '🔢 請輸入房間號碼：',
    'enter_join_password': '🔐 請輸入房間密碼：',
    'room_created': '✅ 房間創建成功！房間號：{}\n請分享給其他成員',
    'join_success': '✅ 成功加入房間：{}',
    'join_failed': '❌ 加入失敗：{}',
    'leave_success': '✅ 已離開房間：{}',
    'leave_failed': '❌ 離開房間失敗',
    'not_in_room': '❌ 請先加入房間',
    'choose_room_to_leave': '🚪 請選擇要離開的房間：',
    'room_notification': '📢 房間通知：{}',
    'current_rooms': '🏠 您當前所在的房間：',
    'no_rooms_joined': '📭 您尚未加入任何房間',
    'ask_reminder': '⏰ 是否需要設置定時提醒？',
    'create_reminder': '創建提醒⏰',
    'skip_reminder': '跳過⏩',
    'select_date': '📅 請選擇提醒日期：',
    'select_time': '⏰ 請選擇提醒時間：',
    'reminder_set': '✅ 提醒設置成功！將在 {} 發送提醒',
    'reminder_message': '🔔 提醒：{}'
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

def leave_room(room_code, user_id):
    """离开房间"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # 获取房间名称用于返回
        c.execute("SELECT room_name FROM rooms WHERE room_code = %s", (room_code,))
        result = c.fetchone()
        if not result:
            return False, "房間不存在"
        
        room_name = result[0]
        
        # 离开房间
        c.execute("""
            DELETE FROM room_members 
            WHERE room_code = %s AND user_id = %s
        """, (room_code, user_id))
        
        conn.commit()
        success = c.rowcount > 0
        
        if success:
            return True, room_name
        else:
            return False, "您不在該房間中"
            
    except Exception as e:
        logger.error(f"Error leaving room: {e}")
        return False, "系統錯誤"
    finally:
        put_db_connection(conn)

def get_user_rooms(user_id):
    """获取用户加入的所有房间"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""
            SELECT r.room_code, r.room_name 
            FROM rooms r
            JOIN room_members rm ON r.room_code = rm.room_code
            WHERE rm.user_id = %s
            ORDER BY rm.joined_at DESC
        """, (user_id,))
        rooms = c.fetchall()
        return rooms
    except Exception as e:
        logger.error(f"Error getting user rooms: {e}")
        return []
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
                FOREIGN KEY(user_id) REFERENCES users(user_id),
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
      
        # 確保房間存在
        c.execute("SELECT 1 FROM rooms WHERE room_code = %s", (room_code,))
        room_exists = c.fetchone()
      
        if not room_exists:
            return None
      
        # 檢查用戶是否在房間中
        c.execute("SELECT 1 FROM room_members WHERE room_code = %s AND user_id = %s", (room_code, user_id))
        if not c.fetchone():
            return None
      
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
        [TEXTS['room_options']],
        [TEXTS['help']]
    ], resize_keyboard=True, one_time_keyboard=False)

def get_room_options_keyboard():
    """房间选项二级菜单"""
    return ReplyKeyboardMarkup([
        [TEXTS['create_room'], TEXTS['join_room']],
        [TEXTS['leave_room']],
        ['⬅️ 返回主菜单']
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
def get_leave_room_keyboard(rooms):
    """离开房间的选择键盘"""
    keyboard = []
    for room_code, room_name in rooms:
        keyboard.append([InlineKeyboardButton(f"{room_name} ({room_code})", callback_data=f'leave_{room_code}')])
    keyboard.append([InlineKeyboardButton('⬅️ 取消', callback_data='cancel_leave')])
    return InlineKeyboardMarkup(keyboard)
def get_reminder_keyboard():
    """提醒选择键盘"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(TEXTS['create_reminder'], callback_data='set_reminder')],
        [InlineKeyboardButton(TEXTS['skip_reminder'], callback_data='skip_reminder')]
    ])
def create_calendar_keyboard():
    """创建日历键盘（基于第二个项目）"""
    now = datetime.datetime.now()
    year, month = now.year, now.month
    
    keyboard = []
    # 第一行 - 月份和年份
    row = [InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="CAL_IGNORE")]
    keyboard.append(row)
    
    # 第二行 - 星期
    row = []
    for day in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]:
        row.append(InlineKeyboardButton(day, callback_data="CAL_IGNORE"))
    keyboard.append(row)
    
    # 日历日期
    my_calendar = calendar.monthcalendar(year, month)
    for week in my_calendar:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
            else:
                callback_data = f"CAL_DAY_{year}_{month}_{day}"
                row.append(InlineKeyboardButton(str(day), callback_data=callback_data))
        keyboard.append(row)
    
    # 导航行
    row = []
    prev_month = now - datetime.timedelta(days=now.day)
    next_month = now + datetime.timedelta(days=31-now.day)
    
    row.append(InlineKeyboardButton("<", callback_data=f"CAL_PREV_{prev_month.year}_{prev_month.month}"))
    row.append(InlineKeyboardButton(" ", callback_data="CAL_IGNORE"))
    row.append(InlineKeyboardButton(">", callback_data=f"CAL_NEXT_{next_month.year}_{next_month.month}"))
    keyboard.append(row)
    
    return InlineKeyboardMarkup(keyboard)
def create_time_selection_keyboard():
    """创建时间选择键盘（基于第二个项目）"""
    keyboard = []
    
    # 小时行
    hours_row = []
    for hour in [9, 10, 11, 12]:
        hours_row.append(InlineKeyboardButton(f"{hour:02d}:00", callback_data=f"TIME_{hour:02d}_00"))
    keyboard.append(hours_row)
    
    hours_row = []
    for hour in [13, 14, 15, 16]:
        hours_row.append(InlineKeyboardButton(f"{hour:02d}:00", callback_data=f"TIME_{hour:02d}_00"))
    keyboard.append(hours_row)
    
    hours_row = []
    for hour in [17, 18, 19, 20]:
        hours_row.append(InlineKeyboardButton(f"{hour:02d}:00", callback_data=f"TIME_{hour:02d}_00"))
    keyboard.append(hours_row)
    
    # 自定义时间行
    keyboard.append([InlineKeyboardButton("自定义时间", callback_data="CUSTOM_TIME")])
    
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
    
    # 首先检查自定义日期和时间的输入
    if 'waiting_custom_date' in context.user_data:
        # 处理自定义日期输入
        try:
            date_str = update.message.text
            datetime.strptime(date_str, "%Y-%m-%d")  # 验证日期格式
            context.user_data['reminder_date'] = date_str
            context.user_data.pop('waiting_custom_date')
            await update.message.reply_text(
                TEXTS['select_time'],
                reply_markup=create_time_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ 日期格式錯誤，請使用 YYYY-MM-DD 格式")
        return
    
    elif 'waiting_custom_time' in context.user_data:
        # 处理自定义时间输入
        try:
            time_str = update.message.text
            datetime.strptime(time_str, "%H:%M")  # 验证时间格式
            date_str = context.user_data.get('reminder_date')
            
            if not date_str or 'last_todo' not in context.user_data:
                await update.message.reply_text("設置失敗，請重新嘗試")
                return
            
            # 解析日期和时间
            reminder_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            now = datetime.now()
            
            if reminder_datetime <= now:
                await update.message.reply_text(
                    "❌ 不能設置過去的時間作為提醒",
                    reply_markup=get_main_keyboard()
                )
                return
            
            # 计算延迟时间（秒）
            delay = (reminder_datetime - now).total_seconds()
            
            # 获取待办信息
            todo_info = context.user_data['last_todo']
            
            # 安排提醒任务
            context.job_queue.run_once(
                send_reminder, 
                delay, 
                data={
                    'room_code': todo_info['room_code'],
                    'task': todo_info['task'],
                    'category': todo_info['category']
                }
            )
            
            await update.message.reply_text(
                TEXTS['reminder_set'].format(reminder_datetime.strftime("%Y-%m-%d %H:%M")),
                reply_markup=get_main_keyboard()
            )
            
            # 清理用户数据
            context.user_data.pop('last_todo', None)
            context.user_data.pop('reminder_date', None)
            context.user_data.pop('waiting_custom_time', None)
            
        except ValueError:
            await update.message.reply_text("❌ 時間格式錯誤，請使用 HH:MM 格式")
        return

    # 房间管理功能
    if message_text == TEXTS['room_options']:
        await update.message.reply_text(
            "🏠 房間管理選項",
            reply_markup=get_room_options_keyboard()
        )
        return
  
    elif message_text == TEXTS['create_room']:
        context.user_data['waiting_room_name'] = True
        await update.message.reply_text(TEXTS['enter_room_name'])
        return
  
    elif message_text == TEXTS['join_room']:
        context.user_data['waiting_room_code'] = True
        await update.message.reply_text(TEXTS['enter_room_code'])
        return
  
    elif message_text == TEXTS['leave_room']:
        rooms = get_user_rooms(user_id)
        if not rooms:
            await update.message.reply_text(
                TEXTS['no_rooms_joined'],
                reply_markup=get_main_keyboard()
            )
            return
        
        await update.message.reply_text(
            TEXTS['choose_room_to_leave'],
            reply_markup=get_leave_room_keyboard(rooms)
        )
        return
  
    elif message_text == '⬅️ 返回主菜单':
        await update.message.reply_text(
            "返回主菜单",
            reply_markup=get_main_keyboard()
        )
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
    
    # 待办事项功能 - 需要选择当前操作的房间
    if message_text in [TEXTS['query_all'], TEXTS['query_category'], TEXTS['add_todo'], TEXTS['delete_todo']]:
        rooms = get_user_rooms(user_id)
        if not rooms:
            await update.message.reply_text(TEXTS['not_in_room'])
            return
        
        # 如果用户只有一个房间，直接使用该房间
        if len(rooms) == 1:
            room_code, room_name = rooms[0]
            context.user_data['current_room'] = room_code
        else:
            # 多个房间时需要用户选择
            context.user_data['pending_operation'] = message_text
            await show_room_selection(update, context, rooms, message_text)
            return
    
    # 获取当前操作的房间
    current_room = context.user_data.get('current_room')
    if not current_room:
        await update.message.reply_text(TEXTS['not_in_room'])
        return
    
    if message_text == TEXTS['query_all']:
        await query_all_todos(update, context, current_room)
    elif message_text == TEXTS['query_category']:
        await choose_category(update, context, 'query')
    elif message_text == TEXTS['add_todo']:
        await choose_category(update, context, 'add')
    elif message_text == TEXTS['delete_todo']:
        await choose_delete(update, context, current_room)
    elif message_text == TEXTS['help']:
        await help_command(update, context)
    else:
        if 'waiting_task' in context.user_data:
            category = context.user_data['waiting_category']
            task = message_text
            try:
                todo_id = add_todo_to_db(current_room, user_id, category, task, context)
                if todo_id:
                    context.user_data['last_todo'] = {
                        'id': todo_id,
                        'category': category,
                        'task': task,
                        'room_code': current_room
                    }
                    await update.message.reply_text(
                        TEXTS['ask_reminder'],
                        reply_markup=get_reminder_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        "❌ 添加失敗，請確認您仍在該房間中",
                        reply_markup=get_main_keyboard()
                    )
            except Exception as e:
                logger.error(f"添加待辦失敗: {e}")
                await update.message.reply_text(
                    "❌ 添加失敗，請稍後重試",
                    reply_markup=get_main_keyboard()
                )
            finally:
                context.user_data.pop('waiting_task', None)
                context.user_data.pop('waiting_category', None)

async def show_room_selection(update, context, rooms, operation):
    """显示房间选择界面"""
    keyboard = []
    for room_code, room_name in rooms:
        keyboard.append([InlineKeyboardButton(
            f"{room_name} ({room_code})", 
            callback_data=f'select_room_{room_code}_{operation}'
        )])
    
    await update.message.reply_text(
        "🏠 請選擇要操作的房間：",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if data.startswith('select_room_'):
        # 处理房间选择
        parts = data.split('_')
        room_code = parts[2]
        operation = parts[3]
        
        context.user_data['current_room'] = room_code
        
        if operation == TEXTS['query_all']:
            await query_all_todos_from_callback(query, context, room_code)
        elif operation == TEXTS['query_category']:
            await choose_category_from_callback(query, context, 'query')
        elif operation == TEXTS['add_todo']:
            await choose_category_from_callback(query, context, 'add')
        elif operation == TEXTS['delete_todo']:
            await choose_delete_from_callback(query, context, room_code)
    
    elif data.startswith('add_category_'):
        category = data.split('_')[2]
        context.user_data['waiting_category'] = category
        context.user_data['waiting_task'] = True
        await query.edit_message_text(TEXTS['enter_task'])
    
    elif data.startswith('query_category_'):
        category = data.split('_')[2]
        room_code = context.user_data.get('current_room')
        if room_code:
            await show_todos_by_category(query, context, room_code, category)
        else:
            await query.edit_message_text(TEXTS['not_in_room'])
    
    elif data.startswith('delete_'):
        room_code = context.user_data.get('current_room')
        if not room_code:
            await query.edit_message_text(TEXTS['not_in_room'])
            return
        
        todo_id = int(data.split('_')[1])
        if delete_todo(room_code, todo_id, context):
            await query.edit_message_text(TEXTS['task_deleted'])
        else:
            await query.edit_message_text("❌ 刪除失敗")
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            reply_markup=get_main_keyboard()
        )
    
    elif data == 'set_reminder':
        # 用户选择设置提醒
        await query.edit_message_text(
            TEXTS['select_date'],
            reply_markup=create_calendar_keyboard()  # 使用新的日历键盘
        )
    
    elif data.startswith('CAL_'):
        # 处理日历回调
        if data == 'CAL_IGNORE':
            return
        
        elif data.startswith('CAL_DAY_'):
            # 用户选择了日期
            parts = data.split('_')
            year, month, day = int(parts[2]), int(parts[3]), int(parts[4])
            context.user_data['reminder_date'] = f"{year}-{month:02d}-{day:02d}"
            
            await query.edit_message_text(
                TEXTS['select_time'],
                reply_markup=create_time_selection_keyboard()
            )
        
        elif data.startswith('CAL_PREV_') or data.startswith('CAL_NEXT_'):
            # 用户切换月份
            parts = data.split('_')
            year, month = int(parts[2]), int(parts[3])
            
            await query.edit_message_text(
                TEXTS['select_date'],
                reply_markup=create_calendar_keyboard(year, month)
            )
    
    # 处理时间回调
    elif data.startswith('TIME_'):
        # 用户选择了预设时间
        parts = data.split('_')
        hour, minute = parts[1], parts[2]
        time_str = f"{hour}:{minute}"
        
        await process_time_selection(query, context, time_str)
    
    elif data == 'CUSTOM_TIME':
        # 用户选择自定义时间
        context.user_data['waiting_custom_time'] = True
        await query.edit_message_text("请输入时间 (HH:MM 格式，例如 14:30):")
    
    elif data == 'skip_reminder':
        # 用户选择跳过提醒
        await query.edit_message_text(
            "已跳過提醒設置",
            reply_markup=get_main_keyboard()
        )
        context.user_data.pop('last_todo', None)
    
    elif data.startswith('remind_date_'):
        # 用户选择了日期 (旧版兼容)
        date_str = data.split('_')[2]
        context.user_data['reminder_date'] = date_str
        await query.edit_message_text(
            TEXTS['select_time'],
            reply_markup=create_time_selection_keyboard()  # 使用新的时间键盘
        )
    
    elif data.startswith('remind_time_'):
        # 用户选择了时间 (旧版兼容)
        time_str = data.split('_')[2]
        await process_time_selection(query, context, time_str)
    
    elif data == 'cancel_reminder':
        # 用户取消设置提醒
        context.user_data.pop('last_todo', None)
        context.user_data.pop('reminder_date', None)
        context.user_data.pop('waiting_custom_time', None)
        await query.edit_message_text(
            "已取消提醒設置",
            reply_markup=get_main_keyboard()
        )
    
    elif data.startswith('leave_'):
        room_code = data.split('_')[1]
        success, message = leave_room(room_code, user_id)
        
        if success:
            await query.edit_message_text(TEXTS['leave_success'].format(message))
            # 如果离开的是当前操作的房间，清除当前房间设置
            if context.user_data.get('current_room') == room_code:
                context.user_data.pop('current_room', None)
        else:
            await query.edit_message_text(TEXTS['leave_failed'])
        
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            reply_markup=get_main_keyboard()
        )
    
    elif data == 'cancel_leave':
        await query.edit_message_text("已取消離開房間")
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            reply_markup=get_main_keyboard()
        )
async def process_time_selection(query, context, time_str):
    """处理时间选择"""
    date_str = context.user_data.get('reminder_date')
    
    if not date_str or 'last_todo' not in context.user_data:
        await query.edit_message_text("設置失敗，請重新嘗試")
        return
    
    try:
        # 解析日期和时间
        reminder_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        now = datetime.now()
        
        if reminder_datetime <= now:
            await query.edit_message_text("❌ 不能設置過去的時間作為提醒")
            return
        
        # 计算延迟时间（秒）
        delay = (reminder_datetime - now).total_seconds()
        
        # 获取待办信息
        todo_info = context.user_data['last_todo']
        
        # 安排提醒任务
        context.job_queue.run_once(
            send_reminder, 
            delay, 
            data={
                'room_code': todo_info['room_code'],
                'task': todo_info['task'],
                'category': todo_info['category']
            }
        )
        
        await query.edit_message_text(
            TEXTS['reminder_set'].format(reminder_datetime.strftime("%Y-%m-%d %H:%M")),
            reply_markup=get_main_keyboard()
        )
        
        # 清理用户数据
        context.user_data.pop('last_todo', None)
        context.user_data.pop('reminder_date', None)
        context.user_data.pop('waiting_custom_time', None)
        
    except Exception as e:
        logger.error(f"設置提醒失敗: {e}")
        await query.edit_message_text("❌ 設置提醒失敗")

async def choose_category(update: Update, context: ContextTypes.DEFAULT_TYPE, operation_type):
    await update.message.reply_text(
        TEXTS['choose_category'],
        reply_markup=get_category_keyboard(operation_type)
    )
async def choose_category_from_callback(query, context: ContextTypes.DEFAULT_TYPE, operation_type):
    await query.edit_message_text(
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
async def query_all_todos_from_callback(query, context: ContextTypes.DEFAULT_TYPE, room_code):
    todos = get_todos(room_code)
    if not todos:
        await query.edit_message_text(TEXTS['no_tasks'])
        return
    
    message = TEXTS['all_tasks'] + '\n\n'
    for i, (_, user_id, category, task) in enumerate(todos, 1):
        category_name = CATEGORIES[category]
        message += f"{i}. {category_name}: {task}\n"
    
    await query.edit_message_text(message)
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
async def send_reminder(context):
    """发送提醒消息"""
    job_data = context.job.data
    room_code = job_data['room_code']
    task = job_data['task']
    category = job_data['category']
    
    category_name = CATEGORIES.get(category, category)
    message = TEXTS['reminder_message'].format(f"{category_name}: {task}")
    
    # 向房间所有成员发送提醒
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id FROM room_members WHERE room_code = %s", (room_code,))
        members = c.fetchall()
        
        for (user_id,) in members:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=message
                )
            except Exception as e:
                logger.error(f"發送提醒給用戶 {user_id} 失敗: {e}")
    except Exception as e:
        logger.error(f"獲取房間成員失敗: {e}")
    finally:
        put_db_connection(conn)
async def choose_delete(update: Update, context: ContextTypes.DEFAULT_TYPE, room_code):
    todos = get_todos(room_code)
    if not todos:
        await update.message.reply_text(TEXTS['no_tasks'])
        return
    
    await update.message.reply_text(
        TEXTS['choose_todo_delete'],
        reply_markup=get_delete_keyboard(todos)
    )
async def choose_delete_from_callback(query, context: ContextTypes.DEFAULT_TYPE, room_code):
    todos = get_todos(room_code)
    if not todos:
        await query.edit_message_text(TEXTS['no_tasks'])
        return
    
    await query.edit_message_text(
        TEXTS['choose_todo_delete'],
        reply_markup=get_delete_keyboard(todos)
    )
def check_env_vars():
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")
def main():
    try:
        check_env_vars()
        init_db_pool()
        init_db()
        
        # 在 Render 上不需要健康检查服务器，因为 Render 有内置的健康检查
        # 可以移除或注释掉健康检查服务器的代码
        # health_thread = threading.Thread(target=run_health_check_server, daemon=True)
        # health_thread.start()
        # logger.info("Health check server started for port detection")
        
        application = Application.builder().token(TOKEN).build()
        
        # 添加处理器
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(callback_query))
        
        # 在 Render 上使用 polling 模式
        logger.info("Starting bot with polling mode...")
        application.run_polling(
            poll_interval=2.0,
            timeout=15,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
            
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
        raise
    finally:
        close_db_pool()

if __name__ == '__main__':
    # 直接调用同步的 main 函数
    main()