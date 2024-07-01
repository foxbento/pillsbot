import os
import datetime
import pytz
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from google.cloud import firestore

user_data = {}

GMT8 = pytz.timezone('Asia/Singapore')

db = firestore.Client()

def get_current_date():
    now = datetime.datetime.now(GMT8)
    if now.hour < 0:
        now = now - datetime.timedelta(days=1)
    return now.date()

def get_user_data(user_id):
    doc_ref = db.collection('users').document(str(user_id))
    doc = doc_ref.get()
    if doc.exists:
        return doc.to_dict()
    else:
        return {'tablet_names': [], 'tablet_data': {}}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Welcome to the Tablet Tracker Bot! Use /addtablet to add a new tablet, /removetablet to remove a tablet, and /track to start tracking your tablets.")

async def handle_new_tablet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    '''
        Add new tablet type
    '''
    user_id = update.effective_user.id
    if context.user_data.get('adding_tablet'):
        new_tablet = update.message.text
        doc_ref = db.collection('users').document(str(user_id))
        doc = doc_ref.get()
        if doc.exists:
            user_data = doc.to_dict()
            if new_tablet in user_data.get('tablet_names', []):
                await update.message.reply_text("This tablet is already being tracked. Please enter a different name.")
            else:
                user_data['tablet_names'] = user_data.get('tablet_names', []) + [new_tablet]
                doc_ref.set(user_data)
                await update.message.reply_text(f"Tablet '{new_tablet}' has been added to tracking.")
        else:
            doc_ref.set({'tablet_names': [new_tablet], 'tablet_data': {}})
            await update.message.reply_text(f"Tablet '{new_tablet}' has been added to tracking.")
        context.user_data['adding_tablet'] = False

async def remove_tablet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    if not user['tablet_names']:
        await update.message.reply_text("No tablets are currently being tracked.")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f'remove_{i}')] for i, name in enumerate(user['tablet_names'])]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a tablet to remove:", reply_markup=reply_markup)


async def track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    '''
    check current pills
    '''
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    if not user['tablet_names']:
        await update.message.reply_text("No tablets have been added yet. Use /addtablet to add a tablet to track.")
        return

    keyboard = [[InlineKeyboardButton(name, callback_data=f'increment_{i}')] for i, name in enumerate(user['tablet_names'])]
    keyboard.append([InlineKeyboardButton("View Counts", callback_data='view')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select a tablet to increment or view counts:", reply_markup=reply_markup)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    '''
    Sets up buttons for user to increment/remove pills
    '''
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    query = update.callback_query
    await query.answer()

    today = get_current_date().isoformat()
    
    if query.data.startswith('increment_'):
        tablet_index = int(query.data.split('_')[1])
        if today not in user['tablet_data']:
            user['tablet_data'][today] = [0] * len(user['tablet_names'])
        user['tablet_data'][today][tablet_index] += 1
        db.collection('users').document(str(user_id)).set(user)
        await query.edit_message_text(f"{user['tablet_names'][tablet_index]} count incremented. Current counts:\n" + get_counts_text(user))
    elif query.data == 'view':
        await query.edit_message_text("Current counts:\n" + get_counts_text(user))
    elif query.data.startswith('remove_'):
        tablet_index = int(query.data.split('_')[1])
        removed_tablet = user['tablet_names'].pop(tablet_index)
        for day in user['tablet_data']:
            if len(user['tablet_data'][day]) > tablet_index:
                user['tablet_data'][day].pop(tablet_index)
        db.collection('users').document(str(user_id)).set(user)
        await query.edit_message_text(f"Tablet '{removed_tablet}' has been removed from tracking.")

async def add_tablet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user = get_user_data(user_id)
    if len(user['tablet_names']) >= 3:
        await update.message.reply_text("You can only track up to 3 tablets. Please remove a tablet before adding a new one.")
        return
    await update.message.reply_text("Please enter the name of the tablet you want to add:")
    context.user_data['adding_tablet'] = True

def get_counts_text(user) -> str:
    today = get_current_date().isoformat()
    if today not in user['tablet_data'] or not user['tablet_names']:
        return "No tablets taken today."
    counts = user['tablet_data'][today]
    return "\n".join(f"{name}: {count}" for name, count in zip(user['tablet_names'], counts))

app = Flask(__name__)

bot_token = os.environ.get('BOT_TOKEN')
if not bot_token:
    raise ValueError("No BOT_TOKEN environment variable set")

application = Application.builder().token(bot_token).build()

# Add handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("addtablet", add_tablet))
application.add_handler(CommandHandler("removetablet", remove_tablet))
application.add_handler(CommandHandler("track", track))
application.add_handler(CallbackQueryHandler(button))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_tablet))

@app.route('/', methods=['POST'])
async def webhook():
    if request.method == "POST":
        await application.update_queue.put(Update.de_json(request.get_json(force=True), application.bot))
    return 'OK'

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)