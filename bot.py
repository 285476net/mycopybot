import telebot
import os
import re
from flask import Flask
from threading import Thread, Timer
import time
from pymongo import MongoClient

# ==========================================
# CONFIGURATION & DATABASE CONNECTION
# ==========================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID'))
MONGO_URL = os.getenv('MONGO_URL')

# MongoDB Connection
client = MongoClient(MONGO_URL)
db = client['telegram_bot_db'] # Database Name
config_col = db['settings']    # Collection Name

bot = telebot.TeleBot(BOT_TOKEN)

# ==========================================
# DATABASE HELPER FUNCTIONS
# ==========================================
def get_config():
    """Database ထဲက Config ကို ဆွဲယူမည်။ မရှိသေးရင် အသစ်ဆောက်မည်။"""
    data = config_col.find_one({"_id": "bot_config"})
    
    if not data:
        # DB မှာ မရှိသေးရင် Env Var က Default တွေကို ယူပြီး DB မှာ အသစ်ဆောက်မယ်
        default_channel = os.getenv('TARGET_CHANNEL_ID')
        new_data = {
            "_id": "bot_config",
            "channel_id": default_channel,
            "authorized_users": [ADMIN_ID]
        }
        config_col.insert_one(new_data)
        return new_data
    return data

def update_channel_id(new_id):
    """Channel ID အသစ်ကို DB မှာ သိမ်းမည်"""
    config_col.update_one({"_id": "bot_config"}, {"$set": {"channel_id": new_id}})

def add_auth_user(user_id):
    """User အသစ်ကို DB မှာ ထည့်မည်"""
    config_col.update_one({"_id": "bot_config"}, {"$addToSet": {"authorized_users": user_id}})

def remove_auth_user(user_id):
    """User ကို DB မှ ဖယ်ရှားမည်"""
    config_col.update_one({"_id": "bot_config"}, {"$pull": {"authorized_users": user_id}})

# ==========================================
# MEMORY CACHE (DB ကို ခဏခဏ မခေါ်ရအောင်)
# ==========================================
# Bot စrun တာနဲ့ DB ထဲက Data ကို ဆွဲတင်ထားမယ်
current_config = get_config()

# Single file တွေအတွက် caption စောင့်ဖို့
pending_files = {}
# Batch (အများကြီး) လာရင် ခဏထိန်းထားဖို့
batch_data = {} 

# ==========================================
# WEB SERVER
# ==========================================
app = Flask('')

@app.route('/')
def home():
    return "Bot is Running with MongoDB! 🤖"

def run_http():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# ==========================================
# ADMIN & AUTH COMMANDS
# ==========================================

def is_authorized(user_id):
    # Memory ထဲက List ကိုပဲ စစ်မယ် (မြန်အောင်လို့)
    # Admin ID ကိုတော့ အမြဲတမ်း ခွင့်ပြုမယ်
    if user_id == ADMIN_ID: return True
    return user_id in current_config.get('authorized_users', [])

@bot.message_handler(commands=['setchannel'])
def set_channel(message):
    if message.from_user.id != ADMIN_ID: return

    try:
        parts = message.text.split()
        if len(parts) == 2:
            new_id = parts[1]
            
            # 1. DB မှာ ပြင်မယ်
            update_channel_id(new_id)
            # 2. Memory မှာ ပြင်မယ် (ချက်ချင်းသက်ရောက်အောင်)
            current_config['channel_id'] = new_id
            
            bot.reply_to(message, f"✅ Database Saved! Target Channel changed to `{new_id}`")
        else:
            bot.reply_to(message, "⚠️ Usage: `/setchannel -100xxxxxxx`")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")

@bot.message_handler(commands=['checkchannel'])
def check_channel(message):
    if message.from_user.id != ADMIN_ID: return
    # DB ထဲက လက်ရှိ Channel ကို ပြမယ်
    bot.reply_to(message, f"📡 Current Target Channel: `{current_config['channel_id']}`")

@bot.message_handler(commands=['auth'])
def add_user(message):
    if message.from_user.id != ADMIN_ID: return
    
    try:
        new_user_id = int(message.text.split()[1])
        
        # DB & Memory Update
        add_auth_user(new_user_id)
        if new_user_id not in current_config['authorized_users']:
             current_config['authorized_users'].append(new_user_id)

        bot.reply_to(message, f"✅ User ID `{new_user_id}` added to Database.")
    except:
        bot.reply_to(message, "⚠️ Usage: `/auth 123456789`")

@bot.message_handler(commands=['unauth'])
def remove_user(message):
    if message.from_user.id != ADMIN_ID: return
    
    try:
        target_id = int(message.text.split()[1])
        if target_id == ADMIN_ID:
            bot.reply_to(message, "❌ Cannot remove Admin.")
            return

        # DB & Memory Update
        remove_auth_user(target_id)
        if target_id in current_config['authorized_users']:
            current_config['authorized_users'].remove(target_id)

        bot.reply_to(message, f"🗑 User ID `{target_id}` removed from Database.")
    except:
        bot.reply_to(message, "Error.")

# ==========================================
# BATCH PROCESSING LOGIC
# ==========================================
def process_batch(chat_id):
    if chat_id not in batch_data:
        return

    messages = batch_data[chat_id]['messages']
    target_channel = current_config['channel_id'] # Config ထဲက Channel ID ကို ယူသုံးမယ်

    if len(messages) > 1:
        bot.send_message(chat_id, f"✅ ဇာတ်ကား {len(messages)} ကား လက်ခံရရှိသည်။ Channel သို့ ပို့နေပါပြီ...")
        
        for msg in messages:
            try:
                original_caption = msg.caption if msg.caption else ""
                
                bot.copy_message(
                    chat_id=target_channel,
                    from_chat_id=chat_id,
                    message_id=msg.message_id,
                    caption=original_caption,
                    parse_mode="Markdown"
                )
                time.sleep(2) 

            except Exception as e:
                print(f"Error sending batch: {e}")
                continue
        
        bot.send_message(chat_id, "✅ အားလုံးပို့ပြီးပါပြီ။")
    
    elif len(messages) == 1:
        msg = messages[0]
        pending_files[chat_id] = {
            'message_id': msg.message_id,
            'from_chat_id': chat_id
        }
        bot.reply_to(msg, "✏️ **ဒီကားအတွက် Caption ရေးပို့ပေးပါ...**")

    if chat_id in batch_data:
        del batch_data[chat_id]

# ==========================================
# HANDLERS
# ==========================================

@bot.message_handler(content_types=['video', 'document'])
def receive_video(message):
    # Check Permission
    if not is_authorized(message.from_user.id):
        bot.reply_to(message, "⛔️ You are not authorized.")
        return

    chat_id = message.chat.id
    
    if chat_id in batch_data and batch_data[chat_id]['timer']:
        batch_data[chat_id]['timer'].cancel()
    
    if chat_id not in batch_data:
        batch_data[chat_id] = {'messages': [], 'timer': None}
    
    batch_data[chat_id]['messages'].append(message)
    
    batch_data[chat_id]['timer'] = Timer(2.0, process_batch, [chat_id])
    batch_data[chat_id]['timer'].start()

@bot.message_handler(func=lambda m: m.chat.id in pending_files, content_types=['text'])
def receive_caption(message):
    if not is_authorized(message.from_user.id): return

    chat_id = message.chat.id
    user_input = message.text
    file_info = pending_files.get(chat_id)
    target_channel = current_config['channel_id']
    
    if not file_info: return

    try:
        final_caption = user_input
        if user_input == "/original":
             bot.send_message(chat_id, "Single File ဖြစ်လို့ Caption ရေးပေးမှရပါမယ်။")
             return

        bot.copy_message(
            chat_id=target_channel,
            from_chat_id=file_info['from_chat_id'],
            message_id=file_info['message_id'],
            caption=final_caption,
            parse_mode="Markdown"
        )
        bot.reply_to(message, "✅ Channel သို့ ပို့ပြီးပါပြီ။")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
    
    del pending_files[chat_id]

# ==========================================
# LINK HANDLING
# ==========================================
@bot.message_handler(func=lambda m: m.text and "t.me/" in m.text)
def handle_post_link(message):
    if not is_authorized(message.from_user.id): return
    if message.chat.id in pending_files: return
    
    link = message.text.strip()
    match = re.search(r"t\.me/([^/]+)/(\d+)", link)
    target_channel = current_config['channel_id']
    
    if match:
        source_username = match.group(1)
        message_id = int(match.group(2))
        source_chat = f"@{source_username}"
        
        bot.reply_to(message, "🔄 Link processing...")

        try:
            bot.copy_message(
                chat_id=target_channel,
                from_chat_id=source_chat,
                message_id=message_id,
                caption=message.text,
                parse_mode="Markdown"
            )
            bot.reply_to(message, "✅ Sent.")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")

# ==========================================
# START
# ==========================================
if __name__ == "__main__":
    keep_alive()
    print("🤖 Bot Started with MongoDB Support...")
    bot.infinity_polling()
