# ==============================================================================
# 🚀 ULTIMATE TELEGRAM FILE STORE BOT (ENTERPRISE EDITION)
# ==============================================================================
# Developed for High Performance, Stateless Architecture & Admin Ease.
# Features:
# - MongoDB Integration (Optional but recommended for Search/Batch)
# - Stateless File Retrieval (Base64)
# - Admin Dashboard (Interactive UI)
# - Broadcast Engine
# - Search Engine
# - Batch/Collection Mode
# - Auto-Delete & Content Protection
# - Shortener Load Balancing
# ==============================================================================

import os
import asyncio
import base64
import logging
import random
import string
import time
import datetime
import aiohttp
import urllib.parse
from flask import Flask
from threading import Thread
from pyrogram import Client, filters, idle, enums
from pyrogram.errors import FloodWait, UserNotParticipant, MessageNotModified, PeerIdInvalid
from pyrogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ChatJoinRequest, 
    Message, 
    CallbackQuery
)

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==============================================================================
# ⚙️ CONFIGURATION (Environment Variables)
# ==============================================================================

# 1. Telegram API Keys (Get from my.telegram.org)
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# 2. Admin & Owner Setup
OWNER_ID = int(os.environ.get("OWNER_ID", "0")) 
# Add multiple admins separated by comma
ADMINS = [int(x) for x in os.environ.get("ADMINS", str(OWNER_ID)).split(",") if x.strip()]

# 3. Channels Setup
DB_CHANNEL = int(os.environ.get("DB_CHANNEL", "0")) # Private Channel for File Storage
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "0")) # Channel for Logs
FORCE_SUB_CHANNELS = [int(x) for x in os.environ.get("FORCE_SUB_CHANNELS", "0").split(",") if x.strip() and x != '0']

# 4. Database (MongoDB - Essential for Advanced Features)
DB_URI = os.environ.get("DB_URI", "")

# 5. Default Settings
PROTECT_CONTENT = os.environ.get("PROTECT_CONTENT", "True").lower() == "true" 
AUTO_DELETE_TIME = int(os.environ.get("AUTO_DELETE_TIME", "600")) # Seconds
APPROVE_DELAY = int(os.environ.get("APPROVE_DELAY", "5")) # Seconds

# 6. Shortener Configuration
# Format: https://api.com/api?api=KEY&url={link}
SHORTENER_URLS = [x.strip() for x in os.environ.get("SHORTENER_API", "").split(",") if x.strip()]

# 7. Custom Caption Template
FILE_CAPTION = os.environ.get("FILE_CAPTION", """
📂 **File Name:** `{file_name}`
💾 **Size:** `{file_size}`

⚠️ __This message will be deleted in {time} mins.__
🤖 **Join Updates:** [Click Here](https://t.me/YourChannel)
""")

# ==============================================================================
# 🏗️ DATABASE ENGINE (MongoDB)
# ==============================================================================
db = None
users_col = None
files_col = None
batches_col = None
settings_col = None

async def connect_mongo():
    global db, users_col, files_col, batches_col, settings_col
    if DB_URI:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            mongo = AsyncIOMotorClient(DB_URI)
            db = mongo["SuperBot"]
            users_col = db["users"]
            files_col = db["files"]
            batches_col = db["batches"]
            settings_col = db["settings"]
            logger.info("✅ MongoDB Connected Successfully!")
        except ImportError:
            logger.error("⚠️ Motor library missing. Install using: pip install motor")
        except Exception as e:
            logger.error(f"⚠️ MongoDB Connection Failed: {e}")

# --- DB Functions ---

async def add_user(user_id, name):
    if users_col is not None:
        if not await users_col.find_one({"_id": user_id}):
            await users_col.insert_one({
                "_id": user_id, 
                "name": name, 
                "is_premium": False, 
                "banned": False, 
                "date": datetime.datetime.now()
            })
            if LOG_CHANNEL:
                try:
                    await app.send_message(
                        LOG_CHANNEL, 
                        f"🥳 **New User Started Bot**\nName: {name}\nID: `{user_id}`"
                    )
                except: pass

async def get_user(user_id):
    if users_col is not None:
        return await users_col.find_one({"_id": user_id})
    return None

async def update_ban_status(user_id, status: bool):
    if users_col is not None:
        await users_col.update_one({"_id": user_id}, {"$set": {"banned": status}})

async def get_total_users():
    return await users_col.count_documents({}) if users_col is not None else 0

async def get_all_users():
    return users_col.find({}) if users_col is not None else []

# Search Indexing
async def save_file_to_db(msg_id, file_name, code, file_size):
    if files_col is not None:
        # Check duplicate
        if not await files_col.find_one({"code": code}):
            await files_col.insert_one({
                "msg_id": msg_id,
                "file_name": file_name,
                "code": code,
                "file_size": file_size,
                "date": datetime.datetime.now()
            })

async def search_files(query):
    if files_col is not None:
        # Regex search (Case insensitive)
        return await files_col.find({"file_name": {"$regex": query, "$options": "i"}}).to_list(length=50)
    return []

# Batch Functions
async def save_batch(range_ids):
    if batches_col is not None:
        batch_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        await batches_col.insert_one({
            "batch_id": batch_id,
            "range_ids": range_ids,
            "date": datetime.datetime.now()
        })
        return batch_id
    return None

async def get_batch(batch_id):
    if batches_col is not None:
        return await batches_col.find_one({"batch_id": batch_id})
    return None

# ==============================================================================
# 🌐 WEB SERVER (Keep-Alive)
# ==============================================================================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "🚀 SuperBot is Running! Status: Online"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# ==============================================================================
# 🧠 UTILITIES & HELPERS
# ==============================================================================

def encode(msg_id):
    """Base64 Encode Message ID"""
    return base64.urlsafe_b64encode(str(msg_id).encode()).decode().strip("=")

def decode(payload):
    """Base64 Decode Message ID"""
    try:
        padding = '=' * (4 - len(payload) % 4)
        return int(base64.urlsafe_b64decode(payload + padding).decode())
    except:
        return 0

def get_size(size):
    """Human Readable File Size"""
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024

async def get_short_link(long_url):
    """Random Shortener Rotation"""
    if not SHORTENER_URLS:
        return long_url 
    
    shortener_template = random.choice(SHORTENER_URLS)
    try:
        # Check if URL needs encoding or already encoded in API logic
        # Simple replacement
        api_url = shortener_template.replace("{link}", urllib.parse.quote(long_url))
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                data = await resp.json()
                # Try common keys
                return data.get("shortenedUrl") or data.get("url") or data.get("short_url") or long_url
    except Exception as e:
        logger.error(f"Shortener Error: {e}")
        return long_url

async def auto_delete_task(bot, msg, delay):
    """Auto Delete Task"""
    await asyncio.sleep(delay)
    try:
        await msg.delete()
    except: pass

# ==============================================================================
# 🤖 BOT CLIENT INITIALIZATION
# ==============================================================================
app = Client("SuperBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ==============================================================================
# 🛡️ FORCE SUBSCRIBE CHECKER
# ==============================================================================
async def check_force_sub(client, user_id):
    if not FORCE_SUB_CHANNELS: return []
    missing = []
    for channel_id in FORCE_SUB_CHANNELS:
        try:
            member = await client.get_chat_member(channel_id, user_id)
            if member.status in [enums.ChatMemberStatus.BANNED, enums.ChatMemberStatus.LEFT]:
                missing.append(channel_id)
        except UserNotParticipant:
            missing.append(channel_id)
        except Exception:
            pass # Bot might not be admin or channel invalid
    return missing

# ==============================================================================
# 🎮 EVENT HANDLERS
# ==============================================================================

# 1. AUTO APPROVE JOIN REQUEST
@app.on_chat_join_request()
async def auto_approve(client, req: ChatJoinRequest):
    if req.chat.id in FORCE_SUB_CHANNELS:
        await asyncio.sleep(APPROVE_DELAY)
        try:
            await client.approve_chat_join_request(req.chat.id, req.user.id)
            await client.send_message(
                req.user.id, 
                f"✅ **Request Approved!**\n\nWelcome to **{req.chat.title}**.\n\n📂 **Go back to the link to access your file.**"
            )
        except: pass

# 2. AUTO INDEXER (DB CHANNEL)
@app.on_message(filters.chat(DB_CHANNEL))
async def index_files(client, message):
    if message.document or message.video or message.audio or message.photo:
        code = encode(message.id)
        link = f"https://t.me/{client.me.username}?start={code}"
        
        # Meta Data
        file_name = "Unknown File"
        file_size = 0
        
        if message.document:
            file_name = message.document.file_name
            file_size = message.document.file_size
        elif message.video:
            file_name = message.video.file_name
            file_size = message.video.file_size
        elif message.audio:
            file_name = message.audio.file_name
            file_size = message.audio.file_size
        elif message.photo:
            file_name = "Photo_File.jpg"
            file_size = 0 # Photo sizes vary
            
        # Save to DB for Search
        await save_file_to_db(message.id, file_name, code, get_size(file_size))
        
        # Add Button
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Get File / Download", url=link)],
            [InlineKeyboardButton("♻️ Share", url=f"https://t.me/share/url?url={link}")]
        ])
        try:
            await message.edit_reply_markup(reply_markup=btn)
        except: pass

# 3. ADMIN DASHBOARD & CALLBACKS
@app.on_message(filters.command("admin") & filters.user(ADMINS))
async def admin_panel(client, message):
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="stats"), InlineKeyboardButton("📢 Broadcast", callback_data="broadcast_setup")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings"), InlineKeyboardButton("👥 Users", callback_data="user_list")],
        [InlineKeyboardButton("❌ Close", callback_data="close_admin")]
    ])
    await message.reply_text("👋 **Welcome Boss!**\n\nChoose an action from the dashboard below:", reply_markup=btn)

@app.on_callback_query(filters.regex("^close_admin$"))
async def close_admin(client, callback):
    await callback.message.delete()

@app.on_callback_query(filters.regex("^stats$"))
async def show_stats(client, callback):
    if users_col is None:
        return await callback.answer("⚠️ MongoDB Not Connected", show_alert=True)
    
    total = await get_total_users()
    files = await files_col.count_documents({}) if files_col is not None else 0
    
    txt = f"📊 **Bot Statistics**\n\n👥 **Users:** `{total}`\n📂 **Indexed Files:** `{files}`\n⚡ **Status:** Online"
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_home")]]))

@app.on_callback_query(filters.regex("^admin_home$"))
async def admin_home(client, callback):
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Stats", callback_data="stats"), InlineKeyboardButton("📢 Broadcast", callback_data="broadcast_setup")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings"), InlineKeyboardButton("👥 Users", callback_data="user_list")],
        [InlineKeyboardButton("❌ Close", callback_data="close_admin")]
    ])
    await callback.message.edit_text("👋 **Welcome Boss!**\n\nChoose an action:", reply_markup=btn)

# 4. START COMMAND & MAIN LOGIC
@app.on_message(filters.command("start"))
async def start_handler(client, message):
    user_id = message.from_user.id
    await add_user(user_id, message.from_user.first_name)
    
    # Check Ban
    user = await get_user(user_id)
    if user and user.get("banned", False):
        await message.reply("🚫 **You are BANNED from using this bot.**\nContact Admin if you think this is a mistake.")
        return

    # Normal Start
    if len(message.command) < 2:
        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔎 Search Files", switch_inline_query_current_chat="")],
            [InlineKeyboardButton("👤 My Account", callback_data="my_account"), InlineKeyboardButton("🆘 Help", callback_data="help")]
        ])
        await message.reply_text(
            f"👋 **Hello {message.from_user.first_name}!**\n\n"
            "I am your **Ultimate File Store Bot**.\n"
            "Send me the file code or search for movies/series below.",
            reply_markup=btn
        )
        return

    payload = message.command[1]

    # --- FORCE SUB CHECK ---
    missing = await check_force_sub(client, user_id)
    if missing:
        buttons = []
        for i, cid in enumerate(missing):
            try:
                chat = await client.get_chat(cid)
                link = chat.invite_link
                buttons.append([InlineKeyboardButton(f"🔐 Join Channel {i+1}", url=link)])
            except:
                # Fallback Logic
                buttons.append([InlineKeyboardButton(f"🔐 Join Channel {i+1}", url=f"https://t.me/c/{str(cid)[4:]}/1")])
        
        orig = payload.replace("verify_", "")
        buttons.append([InlineKeyboardButton("🔄 Try Again", url=f"https://t.me/{client.me.username}?start={orig}")])
        
        await message.reply_text(
            "⚠️ **Access Denied!**\n\nFiles access karne ke liye niche diye gaye channels join karein.",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # --- BATCH / COLLECTION MODE ---
    if payload.startswith("batch_"):
        batch_id = payload.split("_")[1]
        batch_data = await get_batch(batch_id)
        
        if not batch_data:
            await message.reply("❌ **Batch Not Found.**")
            return
            
        status = await message.reply(f"📦 **Processing {len(batch_data['range_ids'])} files...**")
        for msg_id in batch_data['range_ids']:
            try:
                msg = await client.copy_message(user_id, DB_CHANNEL, msg_id, protect_content=PROTECT_CONTENT)
                if AUTO_DELETE_TIME > 0:
                    asyncio.create_task(auto_delete_task(client, msg, AUTO_DELETE_TIME))
                await asyncio.sleep(0.8) # Avoid FloodWait
            except Exception: pass
        await status.delete()
        return

    # --- VERIFY MODE (After Shortener) ---
    if payload.startswith("verify_"):
        real_code = payload.split("_")[1]
        msg_id = decode(real_code)
        
        if msg_id == 0: return await message.reply("❌ Invalid Link")
        
        try:
            # Custom Caption Logic can be added here
            msg = await client.copy_message(user_id, DB_CHANNEL, msg_id, protect_content=PROTECT_CONTENT)
            
            # Send Auto Delete Warning
            if AUTO_DELETE_TIME > 0:
                asyncio.create_task(auto_delete_task(client, msg, AUTO_DELETE_TIME))
                temp_msg = await message.reply(f"⚠️ **Note:** File will be deleted in {AUTO_DELETE_TIME//60} mins to prevent copyright.")
                asyncio.create_task(auto_delete_task(client, temp_msg, AUTO_DELETE_TIME))
                
        except Exception: await message.reply("❌ Error Fetching File.")
        return

    # --- NORMAL MODE (Fresh Link) ---
    code = payload
    msg_id = decode(code)
    if msg_id == 0: return await message.reply("❌ Invalid Link")

    # Premium/Shortener Check
    is_prem = False
    if user and user.get("is_premium", False):
        is_prem = True

    if SHORTENER_URLS and not is_prem:
        verify_link = f"https://t.me/{client.me.username}?start=verify_{code}"
        short_link = await get_short_link(verify_link)
        
        btn = [[InlineKeyboardButton("🔓 Click to Unlock File", url=short_link)]]
        await message.reply_text(
            "🔐 **Secure Link Generated!**\n\nComplete the verification to access your file.",
            reply_markup=InlineKeyboardMarkup(btn)
        )
    else:
        # Direct Send
        try:
            msg = await client.copy_message(user_id, DB_CHANNEL, msg_id, protect_content=PROTECT_CONTENT)
            if AUTO_DELETE_TIME > 0:
                asyncio.create_task(auto_delete_task(client, msg, AUTO_DELETE_TIME))
        except: await message.reply("❌ Error Fetching File.")

# 5. USER PANEL CALLBACKS
@app.on_callback_query(filters.regex("^my_account$"))
async def my_account(client, callback):
    user_id = callback.from_user.id
    name = callback.from_user.first_name
    user = await get_user(user_id)
    
    status = "💎 Premium" if user and user.get("is_premium") else "👤 Free User"
    
    txt = (
        f"👤 **User Profile**\n\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"📛 **Name:** {name}\n"
        f"🏷️ **Status:** {status}"
    )
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))

@app.on_callback_query(filters.regex("^start_back$"))
async def start_back(client, callback):
    btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔎 Search Files", switch_inline_query_current_chat="")],
            [InlineKeyboardButton("👤 My Account", callback_data="my_account"), InlineKeyboardButton("🆘 Help", callback_data="help")]
    ])
    await callback.message.edit_text("👋 **Welcome Back!**", reply_markup=btn)

@app.on_callback_query(filters.regex("^help$"))
async def help_menu(client, callback):
    txt = (
        "🆘 **How to use?**\n\n"
        "1. **Search:** Type the movie name in chat.\n"
        "2. **Files:** Click on any link provided by admin.\n"
        "3. **Batch:** Click on a batch link to get full series.\n\n"
        "**Admin Support:** @YourAdminID"
    )
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="start_back")]]))

# 6. SEARCH HANDLER (TEXT)
@app.on_message(filters.text & filters.private & ~filters.command(["start", "batch", "stats", "broadcast", "admin"]))
async def search_handler(client, message):
    if files_col is None: return
    
    query = message.text
    if len(query) < 3:
        await message.reply("⚠️ Search query too short.")
        return
        
    m = await message.reply("🔎 **Searching Database...**")
    results = await search_files(query)
    
    if not results:
        await m.edit("❌ **No files found matching your query.**")
        return
        
    text = f"🔎 **Search Results for '{query}':**\n\n"
    for file in results:
        link = f"https://t.me/{client.me.username}?start={file['code']}"
        text += f"🎬 [{file['file_name']}]({link}) ({file['file_size']})\n"
    
    await m.edit(text, disable_web_page_preview=True)

# 7. BATCH CREATION (ADMIN)
@app.on_message(filters.command("batch") & filters.user(ADMINS))
async def batch_handler(client, message):
    if batches_col is None:
        await message.reply("⚠️ MongoDB Required for Batches")
        return

    if not message.reply_to_message:
        await message.reply("⚠️ Reply to the **First Message** in DB Channel with `/batch LinkToLastMessage`")
        return

    try:
        start_id = message.reply_to_message.id
        link_parts = message.command[1].split("/")
        end_id = int(link_parts[-1])
        
        range_ids = list(range(start_id, end_id + 1))
        batch_id = await save_batch(range_ids)
        
        link = f"https://t.me/{client.me.username}?start=batch_{batch_id}"
        await message.reply(
            f"✅ **Batch Created Successfully!**\n\n"
            f"📂 **Files:** `{len(range_ids)}`\n"
            f"🔗 **Link:** {link}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Share Batch", url=f"https://t.me/share/url?url={link}")]])
        )
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

# 8. BROADCAST (ADMIN)
@app.on_message(filters.command("broadcast") & filters.user(ADMINS) & filters.reply)
async def broadcast(client, message):
    if users_col is None: return await message.reply("❌ No DB Connected")
    
    status = await message.reply("🚀 **Broadcast Started...**")
    users = await get_all_users()
    total = await get_total_users()
    success = 0
    failed = 0
    
    async for user in users:
        try:
            await message.reply_to_message.copy(user['_id'])
            success += 1
            await asyncio.sleep(0.1) # Respect Rate Limits
        except FloodWait as e:
            await asyncio.sleep(e.value)
            await message.reply_to_message.copy(user['_id'])
            success += 1
        except Exception:
            failed += 1
            
    await status.edit(f"✅ **Broadcast Completed!**\n\n🎯 Total: {total}\n✅ Success: {success}\n❌ Failed: {failed}")

# ==============================================================================
# 🔥 RUNNER
# ==============================================================================
if __name__ == "__main__":
    # Start Web Server
    Thread(target=run_web).start()
    
    # Initialize DB (Async)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(connect_mongo())
    
    print("---------------------------------------")
    print("   🚀 ENTERPRISE BOT STARTED           ")
    print("---------------------------------------")
    
    app.run()