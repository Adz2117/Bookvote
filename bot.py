import os, re, json, sqlite3, hashlib, unicodedata
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "votes.sqlite3")
PAGE_SIZE = 8

with open(os.path.join(os.path.dirname(__file__), "books.json"), encoding="utf-8") as f:
    BOOKS = json.load(f)

def normalize(s: str) -> str:
    s = s.strip().replace("ي", "ی").replace("ك", "ک")
    s = re.sub(r"\s+", " ", s)
    return s.casefold()

def name_key(s: str) -> str:
    # Hash normalized name rather than storing names in the voter table.
    return hashlib.sha256(normalize(s).encode("utf-8")).hexdigest()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS voters (
        name_hash TEXT PRIMARY KEY, display_name TEXT NOT NULL, telegram_user_id INTEGER,
        submitted_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS vote_items (
        name_hash TEXT NOT NULL, book TEXT NOT NULL,
        PRIMARY KEY(name_hash, book))""")
    return conn

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "سلام! 📚 به رأی‌گیری کتاب‌ها خوش اومدی.\n\n"
        "برای شروع /vote رو بزن.\n"
        "می‌تونی کتاب‌ها رو جست‌وجو کنی، چند عنوان رو انتخاب کنی و در پایان رأی رو ثبت کنی.\n"
        "برای لغو هر زمان /cancel رو بزن."
    )

async def vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["stage"] = "name"
    await update.message.reply_text("نام و نام خانوادگی‌ات رو وارد کن:")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("فرایند رأی‌گیری لغو شد. هر وقت خواستی /vote رو بزن.")

async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stage = context.user_data.get("stage")
    text = (update.message.text or "").strip()
    if stage == "name":
        if len(text.split()) < 2 or len(text) < 5:
            await update.message.reply_text("لطفاً نام و نام خانوادگی کامل رو وارد کن.")
            return
        key = name_key(text)
        conn = db()
        exists = conn.execute("SELECT 1 FROM voters WHERE name_hash=?", (key,)).fetchone()
        conn.close()
        if exists:
            context.user_data.clear()
            await update.message.reply_text("با این نام قبلاً رأی ثبت شده. اگر فکر می‌کنی اشتباهه، با مدیر رأی‌گیری تماس بگیر.")
            return
        context.user_data["name"] = text
        context.user_data["name_hash"] = key
        context.user_data["selected"] = set()
        context.user_data["stage"] = "search"
        context.user_data["query"] = ""
        context.user_data["page"] = 0
        await show_books(update, context, edit=False)
    elif stage == "search":
        context.user_data["query"] = text
        context.user_data["page"] = 0
        await show_books(update, context, edit=False)
    else:
        await update.message.reply_text("برای شروع رأی‌گیری /vote رو بزن.")

def filtered_books(context):
    q = normalize(context.user_data.get("query", ""))
    return [(i,b) for i,b in enumerate(BOOKS) if q in normalize(b)]

def keyboard(context):
    selected = context.user_data.get("selected", set())
    found = filtered_books(context)
    page = context.user_data.get("page", 0)
    total_pages = max(1, (len(found)+PAGE_SIZE-1)//PAGE_SIZE)
    page = max(0, min(page, total_pages-1))
    context.user_data["page"] = page
    rows = []
    for i,b in found[page*PAGE_SIZE:(page+1)*PAGE_SIZE]:
        mark = "✅" if b in selected else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {i+1}. {b}", callback_data=f"toggle:{i}")])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data="page:prev"))
    if page<total_pages-1: nav.append(InlineKeyboardButton("بعدی ➡️", callback_data="page:next"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton("🔎 جست‌وجو", callback_data="search"),
                 InlineKeyboardButton(f"ثبت انتخاب‌ها ({len(selected)})", callback_data="done")])
    rows.append([InlineKeyboardButton("🧹 پاک‌کردن انتخاب‌ها", callback_data="clear")])
    return InlineKeyboardMarkup(rows), len(found), page+1, total_pages

async def show_books(update, context, edit=True):
    markup, count, page, pages = keyboard(context)
    q = context.user_data.get("query", "")
    selected = context.user_data.get("selected", set())
    msg = (f"📚 کتاب‌ها: {count} نتیجه برای «{q or 'همه'}»\n"
           f"صفحه {page}/{pages} · انتخاب‌شده: {len(selected)}\n\n"
           "روی عنوان‌ها بزن تا انتخاب/لغو شوند. برای جست‌وجو دکمه 🔎 را بزن.")
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=markup)
    else:
        await update.effective_message.reply_text(msg, reply_markup=markup)

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    if data.startswith("toggle:"):
        i = int(data.split(":")[1])
        b = BOOKS[i]
        selected = context.user_data.setdefault("selected", set())
        if b in selected: selected.remove(b)
        else: selected.add(b)
        await show_books(update, context, edit=True)
    elif data == "page:prev":
        context.user_data["page"] -= 1
        await show_books(update, context, edit=True)
    elif data == "page:next":
        context.user_data["page"] += 1
        await show_books(update, context, edit=True)
    elif data == "search":
        context.user_data["stage"] = "search"
        await q.message.reply_text("عبارت جست‌وجو رو بفرست. برای دیدن همه کتاب‌ها فقط یک نقطه . بفرست.")
    elif data == "clear":
        context.user_data["selected"] = set()
        await show_books(update, context, edit=True)
    elif data == "done":
        selected = sorted(context.user_data.get("selected", set()), key=lambda b: BOOKS.index(b))
        if not selected:
            await q.answer("حداقل یک کتاب انتخاب کن.", show_alert=True)
            return
        context.user_data["pending"] = selected
        rows = [[InlineKeyboardButton("✅ بله، ثبت نهایی", callback_data="confirm"),
                 InlineKeyboardButton("↩️ برگشت", callback_data="back")]]
        await q.message.reply_text("این رأی ثبت بشه؟\n\n" + "\n".join("• "+b for b in selected),
                                   reply_markup=InlineKeyboardMarkup(rows))
    elif data == "back":
        await show_books(update, context, edit=False)
    elif data == "confirm":
        name = context.user_data.get("name")
        key = context.user_data.get("name_hash")
        selected = context.user_data.get("pending", [])
        if not name or not key or not selected:
            await q.message.reply_text("اطلاعات رأی پیدا نشد. دوباره /vote رو بزن.")
            return
        conn = db()
        try:
            conn.execute("INSERT INTO voters(name_hash, display_name, telegram_user_id) VALUES(?,?,?)",
                         (key, name, update.effective_user.id if update.effective_user else None))
            conn.executemany("INSERT INTO vote_items(name_hash, book) VALUES(?,?)", [(key,b) for b in selected])
            conn.commit()
            context.user_data.clear()
            await q.message.reply_text(f"رأی ثبت شد، ممنون! 🙌\nتعداد کتاب‌های انتخابی: {len(selected)}")
        except sqlite3.IntegrityError:
            await q.message.reply_text("با این نام قبلاً رأی ثبت شده. اگر فکر می‌کنی اشتباهه با مدیر تماس بگیر.")
        finally:
            conn.close()

async def results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID or ADMIN_ID == 0:
        await update.message.reply_text("این دستور فقط برای مدیر رأی‌گیری فعال است.")
        return
    conn = db()
    voters = conn.execute("SELECT COUNT(*) FROM voters").fetchone()[0]
    counts = dict(conn.execute("SELECT book, COUNT(*) FROM vote_items GROUP BY book").fetchall())
    conn.close()
    ranked = sorted(BOOKS, key=lambda b: (-counts.get(b,0), BOOKS.index(b)))
    lines = [f"📊 تعداد رأی‌دهندگان: {voters}", ""]
    for i,b in enumerate(ranked,1):
        lines.append(f"{i}. {b} — {counts.get(b,0)} رأی")
    # Telegram message size limit; split into chunks.
    body = "\n".join(lines)
    for start in range(0, len(body), 3500):
        await update.message.reply_text(body[start:start+3500])

async def export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID or ADMIN_ID == 0:
        await update.message.reply_text("این دستور فقط برای مدیر رأی‌گیری فعال است.")
        return
    conn = db()
    counts = dict(conn.execute("SELECT book, COUNT(*) FROM vote_items GROUP BY book").fetchall())
    voters = conn.execute("SELECT COUNT(*) FROM voters").fetchone()[0]
    conn.close()
    text = "رتبه,نام کتاب,تعداد رأی\n" + "\n".join(
        f'{i},"{b.replace(chr(34), chr(34)*2)}",{counts.get(b,0)}'
        for i,b in enumerate(sorted(BOOKS,key=lambda x:(-counts.get(x,0),BOOKS.index(x))),1))
    from telegram import InputFile
    import io
    await update.message.reply_document(InputFile(io.BytesIO(("\ufeff"+text).encode("utf-8")), filename="book-vote-results.csv"),
                                        caption=f"نتایج رأی‌گیری · {voters} رأی‌دهنده")

def main():
    if not TOKEN:
        raise SystemExit("لطفاً متغیر محیطی BOT_TOKEN را تنظیم کنید.")
    if ADMIN_ID == 0:
        raise SystemExit("لطفاً ADMIN_ID (آیدی عددی تلگرام مدیر) را تنظیم کنید.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vote", vote))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("results", results))
    app.add_handler(CommandHandler("export", export))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))
    app.run_polling()

if __name__ == "__main__":
    main()
