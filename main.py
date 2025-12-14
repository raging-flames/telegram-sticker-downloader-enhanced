import asyncio
import glob
import io
import json
import logging
import os
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import telegram
from PIL import Image
from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from tgs2gif import tgs2gif
from webm2gif import webm2gif

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Config globals
admin = []
whitelist = []
config = {}
EXECUTOR = None # Initialized in main or after config load

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_html(
        rf"你好 {user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    limit = config.get('collection_limit', 200)
    timeout = config.get('collection_timeout_min', 30)
    
    help_text = (
        "Telegram 贴纸下载机器人\n\n"
        "指令:\n"
        f"/add - 开始收集单张贴纸（最多{limit}张，{timeout}分钟超时）\n"
        "/pack - 打包发送收集的贴纸\n"
        "/help - 显示此帮助\n\n"
        "功能:\n"
        "1. 直接发送贴纸包链接 -> 下载整套贴纸（收集模式下忽略）\n"
        "2. 直接发送单张贴纸 -> 转换并发送（收集模式下加入队列）\n"
        "   *注: 单张动态贴纸将以 .gif.1 后缀发送，下载后请手动重命名为 .gif*"
    )
    await update.message.reply_text(help_text)

async def add_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in admin:
        return
    try:
        user_id = update.message.text.split(' ')[-1]
        config['whitelist'].append(int(user_id))
        with open('config.json', 'w') as f:
            f.write(json.dumps(config, indent=2))
        global whitelist
        whitelist = config['whitelist']
    except Exception as e:
        await update.message.reply_text(str(e))
    else:
        await update.message.reply_text(f'已添加 {user_id} 到白名单。')

async def list_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in admin:
        return
    await update.message.reply_text(f'当前管理员:{admin}\n当前白名单:{whitelist}')

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pass 

def has_permission(chat_id: int) -> bool:
    if chat_id in admin or chat_id in whitelist:
        return True
    return False

# --- Collection Logic ---
user_collections = {}

async def collection_timeout(user_id, context):
    timeout_min = config.get('collection_timeout_min', 30)
    await asyncio.sleep(timeout_min * 60)
    
    if user_id in user_collections:
        chat_id = user_collections[user_id]['chat_id']
        del user_collections[user_id]
        try:
            await context.bot.send_message(chat_id, f"{timeout_min}分钟未操作，收集已自动结束。")
        except:
            pass

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_permission(update.message.chat_id): return
    
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    limit = config.get('collection_limit', 200)
    timeout_min = config.get('collection_timeout_min', 30)
    
    if user_id in user_collections:
        await update.message.reply_text("您已在收集模式中。发送单张贴纸添加，/pack 打包。")
        # Reset timeout
        user_collections[user_id]['task'].cancel()
        user_collections[user_id]['task'] = asyncio.create_task(collection_timeout(user_id, context))
        return

    task = asyncio.create_task(collection_timeout(user_id, context))
    user_collections[user_id] = {
        'stickers': [],
        'task': task,
        'chat_id': chat_id
    }
    await update.message.reply_text(f"已开启收集模式。\n请发送单张贴纸 (上限{limit})。\n整套贴纸链接将被忽略。\n发送 /pack 完成打包。\n{timeout_min}分钟无操作自动终止。")

async def pack_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_permission(update.message.chat_id): return
    
    user_id = update.effective_user.id
    if user_id not in user_collections:
        await update.message.reply_text("您当前不在收集模式。使用 /add 开始。")
        return
        
    data = user_collections.pop(user_id)
    data['task'].cancel()
    
    stickers = data['stickers']
    if not stickers:
        await update.message.reply_text("未收集到任何贴纸，操作取消。")
        return
        
    title = f"Collection_{int(time.time())}"
    
    context.application.create_task(
        process_stickers_logic(stickers, title, update.message.chat_id, update.message.message_id, context)
    )

# --- Sticker Processing ---

def sanitize_filename(name):
    clean = re.sub(r'[\\/*?:"<>|]', "", name)
    return clean.strip() or "sticker_set"

async def convert_task(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(EXECUTOR, func, *args)

def convert_webp_to_png_sync(input_path, output_path):
    Image.open(input_path).convert('RGBA').save(output_path, 'png')

async def process_single_sticker(sticker, set_folder, semaphore, status_dict):
    async with semaphore:
        status_dict['active_threads'] += 1
        
        file_id = sticker.file_unique_id
        input_path = ""
        try:
            file = await sticker.get_file()
            
            if sticker.is_animated:
                ext = 'tgs'
            elif sticker.is_video:
                ext = 'webm'
            else:
                ext = 'webp'
                
            input_path = f'{set_folder}/{file_id}.{ext}'
            await file.download_to_drive(input_path)
            
            output = None
            if sticker.is_video:
                output = await convert_task(webm2gif, input_path)
                final = f'{set_folder}/{file_id}.gif'
                if output and output != final:
                     shutil.move(output, final)
            elif sticker.is_animated:
                output = await convert_task(tgs2gif, input_path)
                final = f'{set_folder}/{file_id}.gif'
                if output and output != final:
                     shutil.move(output, final)
            else:
                final = f'{set_folder}/{file_id}.png'
                await convert_task(convert_webp_to_png_sync, input_path, final)
                
            status_dict['done'] += 1
            return True
        except Exception as e:
            logger.error(f"Error processing sticker {file_id}: {e}")
            return False
        finally:
            status_dict['active_threads'] -= 1
            if input_path and os.path.exists(input_path):
                try: os.remove(input_path)
                except: pass

async def progress_reporter(msg, status_dict, total):
    last_text = ""
    interval = 1.0
    while status_dict['state'] != 'finished':
        await asyncio.sleep(interval)
        
        text = ""
        if status_dict['state'] == 'downloading':
            done = status_dict.get('done', 0)
            threads = status_dict.get('active_threads', 0)
            text = f"正在下载/转换: {done}/{total}\n当前并发: {threads}"
            
        elif status_dict['state'] == 'pack_upload':
            current_pack = status_dict.get('pack_index', 0)
            total_packs = status_dict.get('pack_count', 0)
            current_size = status_dict.get('current_pack_size', 0)
            s_mb = current_size / (1024*1024)
            
            if current_size > 0:
                if total_packs > 1:
                    text = f"正在发送第 {current_pack}/{total_packs} 部分，大小：{s_mb:.1f}MB"
                else:
                    text = f"正在上传文件，大小：{s_mb:.1f}MB"
            else:
                if total_packs > 1:
                    text = f"正在准备发送第 {current_pack}/{total_packs} 部分..."
                else:
                    text = f"正在准备发送..."
            
        if text and text != last_text:
            try:
                await msg.edit_text(text)
                last_text = text
            except Exception:
                pass

async def process_stickers_logic(stickers, title, chat_id, message_id, context):
    safe_title = sanitize_filename(title)
    base_dir = f'files/{safe_title}'
    
    if os.path.exists(base_dir):
        shutil.rmtree(base_dir)
    os.makedirs(base_dir, exist_ok=True)
    
    is_dynamic = False
    for s in stickers:
        if s.is_animated or s.is_video:
            is_dynamic = True
            break
            
    t_static = config.get('threads_static', 8)
    t_dynamic = config.get('threads_dynamic', 3)
    max_workers = t_dynamic if is_dynamic else t_static
    
    mode_text = "动态" if is_dynamic else "静态"
    msg = await context.bot.send_message(chat_id, f'开始处理 "{safe_title}"\n数量: {len(stickers)}\n模式: {mode_text} (线程: {max_workers})...', reply_to_message_id=message_id)

    status = {
        'state': 'downloading', 
        'done': 0,
        'active_threads': 0,
        'pack_index': 0,
        'pack_count': 0,
        'current_pack_size': 0
    }
    
    reporter = asyncio.create_task(progress_reporter(msg, status, len(stickers)))
    
    sem = asyncio.Semaphore(max_workers)
    tasks = []
    for s in stickers:
        tasks.append(process_single_sticker(s, base_dir, sem, status))
    
    await asyncio.gather(*tasks)
    
    # Cleanup
    all_files = []
    for f in os.listdir(base_dir):
        fpath = os.path.join(base_dir, f)
        if (f.endswith('.gif') or f.endswith('.png')):
            all_files.append(fpath)
        else:
            try: os.remove(fpath)
            except: pass
            
    # Bucketing
    soft_mb = config.get('zip_soft_limit_mb', 45)
    hard_mb = config.get('zip_hard_limit_mb', 49.5)
    
    SOFT_LIMIT = soft_mb * 1024 * 1024
    HARD_LIMIT = hard_mb * 1024 * 1024
    
    batches = []
    current_batch = []
    current_size = 0
    
    all_files.sort()
    
    for fpath in all_files:
        fsize = os.path.getsize(fpath)
        
        can_add = False
        if not current_batch:
            can_add = True
        else:
            if current_size < SOFT_LIMIT and (current_size + fsize) <= HARD_LIMIT:
                can_add = True
        
        if can_add:
            current_batch.append(fpath)
            current_size += fsize
        else:
            batches.append(current_batch)
            current_batch = [fpath]
            current_size = fsize
        
    if current_batch:
        batches.append(current_batch)
        
    status['state'] = 'pack_upload'
    status['pack_count'] = len(batches)
    
    for i, batch in enumerate(batches):
        idx = i + 1
        status['pack_index'] = idx
        
        suffix = f"_{idx:02d}" if len(batches) > 1 else ""
        zip_base = f'files/{safe_title}{suffix}'
        zip_path = f'{zip_base}.zip'
        zip_name = f'{safe_title}{suffix}.zip'
        if len(batches) == 1:
            zip_base = f'files/{safe_title}'
            zip_path = f'{zip_base}.zip'
            zip_name = f'{safe_title}.zip'
        
        if os.path.exists(zip_path):
            os.remove(zip_path)
            
        temp_pack_dir = f'files/temp_pack_{idx}'
        if os.path.exists(temp_pack_dir):
            shutil.rmtree(temp_pack_dir)
        os.makedirs(temp_pack_dir)
        
        for src in batch:
            dst = os.path.join(temp_pack_dir, os.path.basename(src))
            shutil.copy(src, dst)
            
        try:
            await convert_task(shutil.make_archive, zip_base, 'zip', temp_pack_dir)
        except Exception as e:
            await context.bot.send_message(chat_id, f"打包第 {idx} 部分失败: {e}")
            continue
        finally:
            shutil.rmtree(temp_pack_dir)

        fsize = os.path.getsize(zip_path)
        status['current_pack_size'] = fsize
        
        try:
            with open(zip_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id,
                    f, 
                    filename=zip_name,
                    read_timeout=300, connect_timeout=300, write_timeout=300, pool_timeout=300
                )
        except Exception as e:
            err_str = str(e)
            if "Request Entity Too Large" in err_str:
                 await context.bot.send_message(chat_id, f"发送 {zip_name} 失败: 文件过大 ({fsize/1024/1024:.1f}MB)。")
            else:
                 await context.bot.send_message(chat_id, f"发送 {zip_name} 失败: {e}")
             
        if os.path.exists(zip_path):
            os.remove(zip_path)

    status['state'] = 'finished'
    reporter.cancel()
    
    shutil.rmtree(base_dir, ignore_errors=True)
    try: await msg.delete()
    except: pass

async def sticker_set_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_permission(update.message.chat_id): return

    user_id = update.effective_user.id
    if user_id in user_collections:
        return

    raw_name = update.message.text.split('/')[-1]
    
    try:
        sticker_set = await context.bot.get_sticker_set(raw_name)
    except Exception as e:
        await context.bot.send_message(update.message.chat_id, f'获取贴纸包失败: {e}')
        return

    context.application.create_task(
        process_stickers_logic(sticker_set.stickers, sticker_set.title, update.message.chat_id, update.message.message_id, context)
    )

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not has_permission(update.message.chat_id): return
        
    sticker = update.message.sticker
    if not sticker:
        return
        
    user_id = update.effective_user.id
    
    # Collection Mode
    if user_id in user_collections:
        coll = user_collections[user_id]
        limit = config.get('collection_limit', 200)
        
        if len(coll['stickers']) >= limit:
            await update.message.reply_text(f"已达到{limit}张上限，自动开始打包...")
            await pack_command(update, context)
            return
            
        # Check duplicate
        for s in coll['stickers']:
            if s.file_unique_id == sticker.file_unique_id:
                await update.message.reply_text("该贴纸已在列表中。")
                # Reset timeout even if duplicate to keep session alive
                coll['task'].cancel()
                coll['task'] = asyncio.create_task(collection_timeout(user_id, context))
                return

        coll['stickers'].append(sticker)
        coll['task'].cancel()
        coll['task'] = asyncio.create_task(collection_timeout(user_id, context))
        
        await update.message.reply_text(f"已添加到收集队列 ({len(coll['stickers'])}/{limit})")
        return
    
    # Single Mode
    status_msg = await update.message.reply_text("正在转换...")
        
    file_id = sticker.file_unique_id
    temp_dir = f'files/single_{file_id}'
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    
    try:
        file = await sticker.get_file()
        input_path = ""
        output_path = ""
        filename = ""
        
        if sticker.is_animated:
            ext = 'tgs'
            input_path = f'{temp_dir}/{file_id}.{ext}'
            await file.download_to_drive(input_path)
            output_path = await convert_task(tgs2gif, input_path)
            filename = f'{file_id}.gif'
        elif sticker.is_video:
            ext = 'webm'
            input_path = f'{temp_dir}/{file_id}.{ext}'
            await file.download_to_drive(input_path)
            output_path = await convert_task(webm2gif, input_path)
            filename = f'{file_id}.gif'
        else:
            ext = 'webp'
            input_path = f'{temp_dir}/{file_id}.{ext}'
            await file.download_to_drive(input_path)
            output_path = f'{temp_dir}/{file_id}.png'
            await convert_task(convert_webp_to_png_sync, input_path, output_path)
            filename = f'{file_id}.png'

        if output_path and os.path.exists(output_path):
             # Renaming .gif to .gif.1 to avoid telegram conversion to mp4
             final_filename = filename
             if filename.endswith('.gif'):
                 final_filename = filename + '.1'
                 
             with open(output_path, 'rb') as f:
                await update.message.reply_document(
                    document=f, 
                    filename=final_filename,
                    read_timeout=60, write_timeout=60, connect_timeout=60, pool_timeout=60
                )
             await status_msg.delete()
        else:
             await status_msg.edit_text("转换失败")
             
    except Exception as e:
        logger.error(f"Single sticker error: {e}")
        await status_msg.edit_text(f"出错: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def validate_config(conf):
    global admin, whitelist
    admin = conf.get('admin', [])
    whitelist = conf.get('whitelist', [])
    return conf.get('token')

def main() -> None:
    if not os.path.exists('config.json'):
        print("config.json not found")
        return
        
    f = open('config.json', 'r')
    conf = json.loads(f.read())
    f.close()
    
    token = validate_config(conf)
    if not token:
        print("Token not found")
        return
        
    global config
    config = conf
    global EXECUTOR
    max_static = config.get('threads_static', 8)
    # We use a global executor for general tasks, but specific concurrency is handled by Semaphores in tasks.
    # However, create a larger pool just in case.
    EXECUTOR = ThreadPoolExecutor(max_workers=max_static + 2) 

    application = Application.builder().token(token)\
        .read_timeout(100).write_timeout(100).connect_timeout(100).pool_timeout(100)\
        .build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("pack", pack_command))
    application.add_handler(CommandHandler("add_whitelist", add_whitelist)) 
    application.add_handler(CommandHandler("list_whitelist", list_whitelist))

    application.add_handler(MessageHandler(filters.Regex(r'^https://t.me/addstickers/'), sticker_set_handler))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
