import os
import sys
import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from supabase import create_client, Client
from dotenv import load_dotenv

# Try to load environment variables from .env file
load_dotenv()

def check_env_vars():
    required_vars = ['SUPABASE_URL', 'SUPABASE_KEY', 'BOT_TOKEN']
    missing_vars = [var for var in required_vars if var not in os.environ]
    
    if missing_vars:
        print(f"Error: Missing required environment variables: {', '.join(missing_vars)}")
        print("Please set these variables in your Railway project settings.")
        print("\nDebug Information:")
        print(f"Python version: {sys.version}")
        print("Environment variables:")
        for var in os.environ:
            if not var.startswith(('SUPABASE', 'BOT')):  # Don't print sensitive data
                print(f"  {var}: {os.environ.get(var)}")
        return False
    return True

# Load environment variables
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
BOT_TOKEN = os.environ.get('BOT_TOKEN')

if not check_env_vars():
    sys.exit(1)

print(f"SUPABASE_URL: {SUPABASE_URL[:10]}...")  # Print first 10 chars for security
print(f"SUPABASE_KEY: {SUPABASE_KEY[:10]}...")  # Print first 10 chars for security
print(f"BOT_TOKEN: {BOT_TOKEN[:10]}...")  # Print first 10 chars for security

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

GMT8 = pytz.timezone('Asia/Singapore')

def get_current_date():
    now = datetime.datetime.now(GMT8)
    if now.hour < 0:
        now = now - datetime.timedelta(days=1)
    return now.date().isoformat()

async def get_user_data(user_id):
    response = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if len(response.data) == 0:
        new_user = {
            "user_id": user_id,
            "tablet_names": [],
            "tablet_data": {}
        }
        supabase.table("users").insert(new_user).execute()
        return new_user
    return response.data[0]

async def update_user_data(user_id, data):
    supabase.table("users").update(data).eq("user_id", user_id).execute()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to the Tablet Tracker Bot! Use /addtablet to add a new tablet, /removetablet to remove a tablet, and /track to start tracking your tablets.")

async def handle_new_tablet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = await get_user_data(user_id)
    if context.user_data.get('adding_tablet'):
        new_tablet = update.message.text
        if new_tablet in user['tablet_names']:
            await update.message.reply_text("This tablet is already being tracked. Please enter a different name.")
        else:
            user['tablet_names'].append(new_tablet)
            await update_user_data(user_id, user)
            await update.message.reply_text(f"Tablet '{new_tablet}' has been added to tracking.")
        context.user_data['adding_tablet'] = False

async def remove_tablet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = await get_user_data(user_id)
    if not user['tablet_names']:
        await update.message.reply_text("No tablets are currently being tracked.")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f'remove_{i}')] for i, name in enumerate(user['tablet_names'])]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a tablet to remove:", reply_markup=reply_markup)

async def track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = await get_user_data(user_id)
    if not user['tablet_names']:
        await update.message.reply_text("No tablets have been added yet. Use /addtablet to add a tablet to track.")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f'increment_{i}')] for i, name in enumerate(user['tablet_names'])]
    keyboard.append([InlineKeyboardButton("View Counts", callback_data='view')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a tablet to increment or view counts:", reply_markup=reply_markup)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = await get_user_data(user_id)
    query = update.callback_query
    await query.answer()

    today = get_current_date()
    
    if query.data.startswith('increment_'):
        tablet_index = int(query.data.split('_')[1])
        if today not in user['tablet_data']:
            user['tablet_data'][today] = [0] * len(user['tablet_names'])
        
        while len(user['tablet_data'][today]) <= tablet_index:
            user['tablet_data'][today].append(0)
        
        user['tablet_data'][today][tablet_index] += 1
        await update_user_data(user_id, user)
        await query.edit_message_text(f"{user['tablet_names'][tablet_index]} count incremented. Current counts:\n" + get_counts_text(user))
    elif query.data == 'view':
        await query.edit_message_text("Current counts:\n" + get_counts_text(user))
    elif query.data.startswith('remove_'):
        tablet_index = int(query.data.split('_')[1])
        removed_tablet = user['tablet_names'].pop(tablet_index)
        for day in user['tablet_data']:
            if len(user['tablet_data'][day]) > tablet_index:
                user['tablet_data'][day].pop(tablet_index)
        await update_user_data(user_id, user)
        await query.edit_message_text(f"Tablet '{removed_tablet}' has been removed from tracking.")

async def add_tablet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Please enter the name of the tablet you want to add:")
    context.user_data['adding_tablet'] = True

def get_counts_text(user) -> str:
    today = get_current_date()
    if today not in user['tablet_data'] or not user['tablet_names']:
        return "No tablets taken today."
    counts = user['tablet_data'][today]
    return "\n".join(f"{name}: {counts[i] if i < len(counts) else 0}" for i, name in enumerate(user['tablet_names']))

def main() -> None:
    print("Starting the Telegram Bot...")
    application = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addtablet", add_tablet))
    application.add_handler(CommandHandler("removetablet", remove_tablet))
    application.add_handler(CommandHandler("track", track))
    application.add_handler(CallbackQueryHandler(button))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_tablet))

    # Start the bot
    print("Bot is now running. Press Ctrl-C to stop.")
    application.run_polling()

if __name__ == "__main__":
    main()