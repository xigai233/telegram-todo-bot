import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Get bot token from environment variable (for security)
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# In-memory storage for todos (for demo purposes)
user_todos = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when the command /start is issued."""
    await update.message.reply_text('Hello! I am your Todo Bot. Use /add, /list, /done commands to manage your tasks.')

async def add_todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new todo item."""
    user_id = update.message.from_user.id
    task = ' '.join(context.args)
    
    if not task:
        await update.message.reply_text('Please provide a task. Usage: /add Buy groceries')
        return
    
    if user_id not in user_todos:
        user_todos[user_id] = []
    
    user_todos[user_id].append(task)
    await update.message.reply_text(f'Added: {task}')

async def list_todos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all todo items."""
    user_id = update.message.from_user.id
    
    if user_id not in user_todos or not user_todos[user_id]:
        await update.message.reply_text('You have no tasks!')
        return
    
    tasks = '\n'.join([f'{i+1}. {task}' for i, task in enumerate(user_todos[user_id])])
    await update.message.reply_text(f'Your tasks:\n{tasks}')

async def done_todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark a todo item as done."""
    user_id = update.message.from_user.id
    
    if user_id not in user_todos or not user_todos[user_id]:
        await update.message.reply_text('You have no tasks to complete!')
        return
    
    try:
        task_index = int(context.args[0]) - 1 if context.args else 0
        completed_task = user_todos[user_id].pop(task_index)
        await update.message.reply_text(f'Completed: {completed_task}')
    except (IndexError, ValueError):
        await update.message.reply_text('Please provide a valid task number. Usage: /done 1')

def main():
    """Start the bot."""
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        return
    
    # Create the Application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_todo))
    application.add_handler(CommandHandler("list", list_todos))
    application.add_handler(CommandHandler("done", done_todo))
    
    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
