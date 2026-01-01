import telebot
import os
import re
from flask import Flask
from threading import Thread, Timer
import time

# ==========================================
# CONFIGURATION
# ==========================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
TARGET_CHANNEL_ID = os.getenv('TARGET_CHANNEL_ID') 

bot = telebot.TeleBot(BOT_TOKEN)

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
    return "Bot is Running! 🤖"

def run_http():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)))

def keep_alive():
    t = Thread(target=run_http)
    t.start()

# ==========================================
# BATCH PROCESSING LOGIC (အဓိက အပိုင်း)
# ==========================================
def process_batch(chat_id):
    """
    အချိန်ပြည့်သွားတဲ့အခါ ဒီ Function က အလုပ်လုပ်ပါမယ်။
    List ထဲမှာ Message ဘယ်နှစ်စောင်ရှိလဲ စစ်ပါမယ်။
    """
    if chat_id not in batch_data:
        return

    messages = batch_data[chat_id]['messages']
    
    # --- ၁။ အများကြီး Select မှတ်ပြီး ပို့လာခဲ့လျှင် (Batch) ---
    if len(messages) > 1:
        bot.send_message(chat_id, f"✅ ဇာတ်ကား {len(messages)} ကား လက်ခံရရှိသည်။ Channel သို့ ပို့နေပါပြီ...")
        
        for msg in messages:
            try:
                original_caption = msg.caption if msg.caption else ""
                
                bot.copy_message(
                    chat_id=TARGET_CHANNEL_ID,
                    from_chat_id=chat_id,
                    message_id=msg.message_id,
                    caption=original_caption,
                    parse_mode="Markdown"
                )
                
                # 🔥 ဒီနေရာလေးမှာ ၁ စက္ကန့် (သို့) ၂ စက္ကန့် နားခိုင်းလိုက်ပါ
                time.sleep(2) 

            except Exception as e:
                print(f"Error sending batch: {e}")
                # Error တက်လဲ ဆက်လုပ်ခိုင်းမယ်
                continue
        
        bot.send_message(chat_id, "✅ အားလုံးပို့ပြီးပါပြီ။")
    
    # --- ၂။ တစ်စောင်တည်း ပို့လာခဲ့လျှင် (Single) ---
    elif len(messages) == 1:
        msg = messages[0]
        # Single logic အတိုင်း pending list ထဲထည့်ပြီး Caption တောင်းမယ်
        pending_files[chat_id] = {
            'message_id': msg.message_id,
            'from_chat_id': chat_id
        }
        bot.reply_to(msg, "✏️ **ဒီကားအတွက် Caption ရေးပို့ပေးပါ...**")

    # ပြီးရင် Data ရှင်းထုတ်မယ်
    if chat_id in batch_data:
        del batch_data[chat_id]

# ==========================================
# HANDLERS
# ==========================================

@bot.message_handler(content_types=['video', 'document'])
def receive_video(message):
    chat_id = message.chat.id
    
    # အကယ်၍ အရင် Timer ရှိနေရင် ဖျက်လိုက်မယ် (Reset လုပ်မယ်)
    if chat_id in batch_data and batch_data[chat_id]['timer']:
        batch_data[chat_id]['timer'].cancel()
    
    # Data အသစ်မရှိသေးရင် Dictionary ဆောက်မယ်
    if chat_id not in batch_data:
        batch_data[chat_id] = {'messages': [], 'timer': None}
    
    # Message ကို List ထဲ ထည့်သိမ်းမယ်
    batch_data[chat_id]['messages'].append(message)
    
    # Timer အသစ်စမယ် (2 စက္ကန့် စောင့်မယ်)
    # 2 စက္ကန့်အတွင်း နောက်ထပ် Video မဝင်လာတော့မှ process_batch ကို အလုပ်လုပ်ခိုင်းမယ်
    batch_data[chat_id]['timer'] = Timer(2.0, process_batch, [chat_id])
    batch_data[chat_id]['timer'].start()

@bot.message_handler(func=lambda m: m.chat.id in pending_files, content_types=['text'])
def receive_caption(message):
    chat_id = message.chat.id
    user_input = message.text
    file_info = pending_files.get(chat_id)
    
    if not file_info:
        # Batch process ကြောင့် ဝင်လာတဲ့ text ဖြစ်နိုင်လို့ ဘာမှမလုပ်ဘဲ ကျော်မယ်
        return

    try:
        final_caption = user_input
        
        # /original ဆိုရင်တော့ မူရင်းအတိုင်းထားမယ် (Logic အရ Text က မူရင်းမရှိနိုင်လို့ user input ပဲယူတာ ပိုမှန်)
        if user_input == "/original":
             bot.send_message(chat_id, "Single File ဖြစ်လို့ Caption ရေးပေးမှရပါမယ်။")
             return

        bot.copy_message(
            chat_id=TARGET_CHANNEL_ID,
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
# LINK HANDLING (Optional - မူရင်းအတိုင်း)
# ==========================================
@bot.message_handler(func=lambda m: m.text and "t.me/" in m.text)
def handle_post_link(message):
    if message.chat.id in pending_files: return # Caption တောင်းနေတုန်း Link ပို့ရင် မလုပ်ဘူး
    
    link = message.text.strip()
    match = re.search(r"t\.me/([^/]+)/(\d+)", link)
    
    if match:
        source_username = match.group(1)
        message_id = int(match.group(2))
        source_chat = f"@{source_username}"
        
        bot.reply_to(message, "🔄 Link processing...")

        try:
            bot.copy_message(
                chat_id=TARGET_CHANNEL_ID,
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
    print("🤖 Bot Started...")
    bot.infinity_polling()

