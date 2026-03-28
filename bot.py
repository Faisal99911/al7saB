
# -*- coding: utf-8 -*-

"""
بوت تليجرام متقدم لرصد تفاعل الأعضاء في الشات والمكالمات.

الميزات:
- رصد تفاعل الشات: احتساب ثانية واحدة لكل كلمة مرسلة.
- رصد تفاعل المكالمات: تتبع مدة المكالمات الصوتية/المرئية.
- حفظ البيانات: حفظ تلقائي لبيانات التفاعل في ملفات JSON.
- تقرير أسبوعي: إرسال تقرير تلقائي بأكثر المتفاعلين إلى المجموعات المحددة.
- إدارة المجموعات: أوامر لإضافة/إزالة المجموعات من قائمة تلقي التقارير.
"""

import asyncio
import datetime
import json
import re
from telethon import TelegramClient, events, types
from telethon.errors import ChatAdminRequiredError, UserNotParticipantError
from functools import wraps

# --- 1. الإعدادات والثوابت الأساسية ---

API_ID = 34257542
API_HASH = '614a1b5c5b712ac6de5530d5c571c42a'
BOT_TOKEN = '8574757379:AAF0oDI-L00mf7xDfONyOY17lLplPSo58xA' # توكن البوت الجديد
OWNER_ID = 1486879970  # معرف المالك (استبدله بمعرف حسابك في تيليجرام)

# مسارات ملفات حفظ البيانات
CHAT_ACTIVITY_FILE = 'chat_activity.json'
CALL_ACTIVITY_FILE = 'call_activity.json'
ACTIVE_CALLS_FILE = 'active_calls.json'
LAST_REPORT_DATE_FILE = 'last_report_date.json'
REPORT_GROUPS_FILE = 'report_groups.json'

# --- 2. تهيئة البوت ---

client = TelegramClient('activity_session', API_ID, API_HASH)

# --- 3. حاويات البيانات (سيتم تحميلها من الملفات) ---

user_chat_activity = {}  # {user_id: total_chat_seconds}
user_call_activity = {}  # {user_id: total_call_seconds}
active_calls = {}        # {chat_id: {user_id: call_start_datetime}}
last_report_date = None  # تاريخ آخر تقرير أسبوعي تم إرساله
report_groups = []       # قائمة بمعرفات المجموعات التي تتلقى التقارير

# --- 4. دوال حفظ وتحميل البيانات (Persistence) ---

async def load_data():
    """تحميل البيانات من ملفات JSON."""
    global user_chat_activity, user_call_activity, active_calls, last_report_date, report_groups
    try:
        with open(CHAT_ACTIVITY_FILE, 'r', encoding='utf-8') as f:
            user_chat_activity = {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        user_chat_activity = {}

    try:
        with open(CALL_ACTIVITY_FILE, 'r', encoding='utf-8') as f:
            user_call_activity = {int(k): v for k, v in json.load(f).items()}
    except (FileNotFoundError, json.JSONDecodeError):
        user_call_activity = {}

    try:
        with open(ACTIVE_CALLS_FILE, 'r', encoding='utf-8') as f:
            loaded_active_calls = json.load(f)
            active_calls = {
                int(chat_id): {int(user_id): datetime.datetime.fromisoformat(start_time_str)
                               for user_id, start_time_str in users_in_call.items()}
                for chat_id, users_in_call in loaded_active_calls.items()
            }
    except (FileNotFoundError, json.JSONDecodeError):
        active_calls = {}
    
    try:
        with open(LAST_REPORT_DATE_FILE, 'r', encoding='utf-8') as f:
            date_str = json.load(f)
            if date_str: last_report_date = datetime.datetime.fromisoformat(date_str)
    except (FileNotFoundError, json.JSONDecodeError):
        last_report_date = None

    try:
        with open(REPORT_GROUPS_FILE, 'r', encoding='utf-8') as f:
            report_groups = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        report_groups = []

    print("تم تحميل البيانات بنجاح.")

async def save_data():
    """حفظ البيانات إلى ملفات JSON."""
    try:
        with open(CHAT_ACTIVITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_chat_activity, f, ensure_ascii=False, indent=4)
        with open(CALL_ACTIVITY_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_call_activity, f, ensure_ascii=False, indent=4)
        
        serializable_active_calls = {
            chat_id: {user_id: start_time.isoformat()
                           for user_id, start_time in users_in_call.items()}
            for chat_id, users_in_call in active_calls.items()
        }
        with open(ACTIVE_CALLS_FILE, 'w', encoding='utf-8') as f:
            json.dump(serializable_active_calls, f, ensure_ascii=False, indent=4)
        
        with open(LAST_REPORT_DATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(last_report_date.isoformat() if last_report_date else None, f, ensure_ascii=False, indent=4)
        
        with open(REPORT_GROUPS_FILE, 'w', encoding='utf-8') as f:
            json.dump(report_groups, f, ensure_ascii=False, indent=4)
        print("تم حفظ البيانات بنجاح.")
    except Exception as e:
        print(f"خطأ أثناء حفظ البيانات: {e}")

# --- 5. دوال مساعدة ---

async def get_user_name(user_id):
    """جلب اسم المستخدم من معرفه."""
    try:
        user = await client.get_entity(user_id)
        return user.first_name or f"المستخدم {user_id}"
    except Exception:
        return f"المستخدم {user_id}"

def format_duration(seconds):
    """تحويل الثواني إلى تنسيق Hh Mm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    
    if not parts:
        return "0m" # إذا كانت المدة أقل من دقيقة
    return " ".join(parts)

async def is_owner(event):
    """التحقق إذا كان المرسل هو المالك."""
    return event.sender_id == OWNER_ID

def owner_only(func):
    """مزخرف (Decorator) للتحقق من أن المستخدم هو المالك فقط."""
    @wraps(func)
    async def wrapped(event, *args, **kwargs):
        if await is_owner(event):
            return await func(event, *args, **kwargs)
        return await event.reply("عذراً، هذا الأمر متاح للمالك فقط. 🚫")
    return wrapped

# --- 6. معالجات أحداث البوت (Event Handlers) ---

@client.on(events.NewMessage(incoming=True, outgoing=False))
async def chat_activity_handler(event):
    """يرصد تفاعل الشات ويحسب الثواني بناءً على عدد الكلمات."""
    if event.is_private: return # تجاهل الرسائل الخاصة
    if event.sender_id is None: return # تجاهل الرسائل بدون مرسل
    if event.text:
        word_count = len(event.text.split())
        user_chat_activity[event.sender_id] = user_chat_activity.get(event.sender_id, 0) + (word_count * 10)
        await save_data()

@client.on(events.VoiceChat(chats=None))
async def call_activity_handler(event):
    """يرصد تفاعل المكالمات الصوتية/المرئية."""
    chat_id = event.chat_id
    user_id = event.user_id

    if not chat_id or not user_id: return

    if event.left:
        # المستخدم غادر المكالمة
        if chat_id in active_calls and user_id in active_calls[chat_id]:
            start_time = active_calls[chat_id].pop(user_id)
            duration = (datetime.datetime.now() - start_time).total_seconds()
            user_call_activity[user_id] = user_call_activity.get(user_id, 0) + duration
            await save_data()
    elif event.joined:
        # المستخدم انضم للمكالمة
        if chat_id not in active_calls:
            active_calls[chat_id] = {}
        active_calls[chat_id][user_id] = datetime.datetime.now()
        await save_data()



# --- 7. أوامر إدارة مجموعات التقارير ---
@client.on(events.NewMessage(pattern=r'^/addreportgroup$'))
@owner_only
async def add_report_group(event):
    if event.is_private: return await event.reply("هذا الأمر يعمل فقط في المجموعات. ❌")
    chat_id = event.chat_id
    if chat_id not in report_groups:
        report_groups.append(chat_id)
        await save_data()
        await event.reply("تمت إضافة هذه المجموعة إلى قائمة المجموعات التي تتلقى التقارير الأسبوعية. ✅")
    else:
        await event.reply("هذه المجموعة موجودة بالفعل في قائمة التقارير. ℹ️")

@client.on(events.NewMessage(pattern=r'^/removereportgroup$'))
@owner_only
async def remove_report_group(event):
    if event.is_private: return await event.reply("هذا الأمر يعمل فقط في المجموعات. ❌")
    chat_id = event.chat_id
    if chat_id in report_groups:
        report_groups.remove(chat_id)
        await save_data()
        await event.reply("تمت إزالة هذه المجموعة من قائمة المجموعات التي تتلقى التقارير الأسبوعية. ❌")
    else:
        await event.reply("هذه المجموعة ليست في قائمة التقارير أصلاً. ℹ️")

@client.on(events.NewMessage(pattern=r'^/listreportgroups$'))
@owner_only
async def list_report_groups(event):
    if not report_groups:
        return await event.reply("لا توجد مجموعات مسجلة لتلقي التقارير الأسبوعية. ℹ️")
    
    group_names = []
    for chat_id in report_groups:
        try:
            chat = await client.get_entity(chat_id)
            group_names.append(f"- {chat.title} (`{chat_id}`)")
        except Exception:
            group_names.append(f"- مجموعة غير معروفة (`{chat_id}`)")
    
    await event.reply("**المجموعات التي تتلقى التقارير الأسبوعية:**\n" + "\n".join(group_names))

@client.on(events.NewMessage(pattern=r'^/generatereport$'))
@owner_only
async def manual_generate_report(event):
    if event.is_private: return await event.reply("هذا الأمر يعمل فقط في المجموعات. ❌")
    await event.reply("جاري إنشاء التقرير الأسبوعي يدوياً... 📊")
    await generate_weekly_report(event.chat_id) # إرسال التقرير للمجموعة التي صدر منها الأمر

# --- 8. وظيفة إنشاء التقرير الأسبوعي ---
async def generate_weekly_report(chat_id):
    """ينشئ ويرسل تقريراً أسبوعياً عن تفاعل الأعضاء."""
    global user_chat_activity, user_call_activity, last_report_date

    all_activity = {}
    for user_id, chat_sec in user_chat_activity.items():
        all_activity[user_id] = all_activity.get(user_id, 0) + chat_sec
    for user_id, call_sec in user_call_activity.items():
        all_activity[user_id] = all_activity.get(user_id, 0) + call_sec
    
    if not all_activity:
        await client.send_message(chat_id, "لا توجد بيانات تفاعل لهذا الأسبوع حتى الآن. 😔")
        return

    sorted_activity = sorted(all_activity.items(), key=lambda item: item[1], reverse=True)

    report_message = "✨ **تقرير التفاعل الأسبوعي** ✨\n\n"
    report_message += "إليكم قائمة بأكثر الأعضاء تفاعلاً هذا الأسبوع:\n\n"

    for i, (user_id, total_seconds) in enumerate(sorted_activity[:15]): # عرض أول 10 متفاعلين
        user_name = await get_user_name(user_id)
        chat_duration = format_duration(user_chat_activity.get(user_id, 0))
        call_duration = format_duration(user_call_activity.get(user_id, 0))
        total_duration = format_duration(total_seconds)
        report_message += f"{i+1}. [{user_name}](tg://user?id={user_id})\n"
        report_message += f"   • الشات: `{chat_duration}`\n"
        report_message += f"   • المكالمات: `{call_duration}`\n"
        report_message += f"   • الإجمالي: `{total_duration}`\n\n"
    
    report_message += "\nشكرًا لتفاعلكم الرائع! استمروا في إثراء المجموعة. 🚀"

    await client.send_message(chat_id, report_message, parse_mode='md')

    # إعادة تعيين بيانات الأسبوع الجديد
    user_chat_activity = {}
    user_call_activity = {}
    last_report_date = datetime.datetime.now()    
    await save_data()

@client.on(events.NewMessage(pattern=r'^(تفاعل|/تفاعل)$'))
@owner_only
async def owner_activity_report(event):
    """أمر خاص بالمالك لعرض قائمة المتفاعلين حالياً."""
    if event.is_private: return await event.reply("هذا الأمر يعمل فقط في المجموعات. ❌")
    await event.reply("جاري إعداد قائمة المتفاعلين... 📊")
    await generate_current_activity_report(event.chat_id)

async def generate_current_activity_report(chat_id):
    """ينشئ ويرسل تقريراً فورياً عن تفاعل الأعضاء دون إعادة تعيين البيانات."""
    all_activity = {}
    for user_id, chat_sec in user_chat_activity.items():
        all_activity[user_id] = all_activity.get(user_id, 0) + chat_sec
    for user_id, call_sec in user_call_activity.items():
        all_activity[user_id] = all_activity.get(user_id, 0) + call_sec
    
    if not all_activity:
        await client.send_message(chat_id, "لا توجد بيانات تفاعل حتى الآن. 😔")
        return

    sorted_activity = sorted(all_activity.items(), key=lambda item: item[1], reverse=True)

    report_message = "✨ **قائمة المتفاعلين الحالية** ✨\n\n"
    report_message += "إليكم قائمة بأكثر الأعضاء تفاعلاً حتى الآن:\n\n"

    for i, (user_id, total_seconds) in enumerate(sorted_activity[:15]): # عرض أول 15 متفاعلاً
        user_name = await get_user_name(user_id)
        chat_duration = format_duration(user_chat_activity.get(user_id, 0))
        call_duration = format_duration(user_call_activity.get(user_id, 0))
        total_duration = format_duration(total_seconds)
        report_message += f"{i+1}. [{user_name}](tg://user?id={user_id})\n"
        report_message += f"   • الشات: `{chat_duration}`\n"
        report_message += f"   • المكالمات: `{call_duration}`\n"
        report_message += f"   • الإجمالي: `{total_duration}`\n\n"
    
    report_message += "\nاستمروا في التفاعل! 🚀"

    await client.send_message(chat_id, report_message, parse_mode='md')

# --- 10. مهمة جدولة التقرير الأسبوعي ---
async def weekly_report_scheduler():
    """مهمة تعمل في الخلفية لجدولة إرسال التقرير الأسبوعي."""
    global last_report_date
    while True:
        now = datetime.datetime.now()
        # التحقق إذا مر أسبوع على آخر تقرير (أو إذا لم يتم إرسال تقرير من قبل)
        # يمكن تعديل الشرط ليناسب يوم معين من الأسبوع (مثلاً now.weekday() == 4 ليوم الجمعة)
        if last_report_date is None or (now - last_report_date).days >= 7:
            print("جاري إرسال التقرير الأسبوعي إلى المجموعات المسجلة...")
            for chat_id in report_groups:
                try:
                    await generate_weekly_report(chat_id)
                    print(f"تم إرسال التقرير الأسبوعي للمجموعة: {chat_id}")
                except Exception as e:
                    print(f"خطأ أثناء إرسال التقرير للمجموعة {chat_id}: {e}")
            
            # تحديث تاريخ آخر تقرير بعد إرسال جميع التقارير
            last_report_date = datetime.datetime.now()
            await save_data()

        await asyncio.sleep(datetime.timedelta(days=1).total_seconds()) # التحقق كل 24 ساعة

# --- 10. تشغيل البوت ---

async def main():
    """الدالة الرئيسية لتشغيل البوت."""
    await load_data() # تحميل البيانات عند بدء التشغيل
    await client.start(bot_token=BOT_TOKEN)
    print("البوت يعمل الآن بنجاح...")
    
    # بدء مهمة جدولة التقرير الأسبوعي في الخلفية
    asyncio.create_task(weekly_report_scheduler())

    # حلقة حفظ البيانات الدورية (لضمان حفظ التغييرات الأخرى)
    while True:
        await save_data()
        await asyncio.sleep(60) # حفظ كل دقيقة

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("تم إيقاف البوت يدوياً.")
    except Exception as e:
        print(f"حدث خطأ غير متوقع في التشغيل الرئيسي: {e}")
