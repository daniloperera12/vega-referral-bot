# requirements.txt
# aiogram==3.0.0
# asyncpg
# sqlalchemy
# python-dotenv

import asyncio
import logging
import random
import string
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.sql import func
import os
from dotenv import load_dotenv

load_dotenv()

# ==================== CONFIG ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/vega_bot")
ADMIN_IDS = [int(id) for id in os.getenv("ADMIN_IDS", "").split(",")]
BASE_URL = os.getenv("BASE_URL", "https://t.me/your_bot_username")  # for referral links

logging.basicConfig(level=logging.INFO)

# ==================== DATABASE ====================
Base = declarative_base()
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

class Applicant(Base):
    __tablename__ = "applicants"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    reddit_username = Column(String, nullable=True)
    experience = Column(Text, nullable=True)
    skills = Column(Text, nullable=True)
    portfolio_size = Column(String, nullable=True)
    why_you = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending, approved, rejected, banned
    applied_at = Column(DateTime, default=func.now())
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(Integer, nullable=True)

class Referrer(Base):
    __tablename__ = "referrers"
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    referral_code = Column(String, unique=True, nullable=False)
    referral_link = Column(String, unique=True, nullable=False)
    total_conversions = Column(Integer, default=0)
    total_earned = Column(Float, default=0.0)
    pending_earned = Column(Float, default=0.0)
    rank = Column(String, default="bronze")
    created_at = Column(DateTime, default=func.now())

class Referral(Base):
    __tablename__ = "referrals"
    id = Column(Integer, primary_key=True)
    referrer_telegram_id = Column(Integer, nullable=False)
    referred_telegram_id = Column(Integer, nullable=True)
    referred_email = Column(String, nullable=True)
    status = Column(String, default="pending")  # pending, zoom_booked, verified, onboarded, paid
    referral_link_used = Column(String, nullable=False)
    created_at = Column(DateTime, default=func.now())
    onboarded_at = Column(DateTime, nullable=True)
    first_payment_at = Column(DateTime, nullable=True)

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    referrer_telegram_id = Column(Integer, nullable=False)
    referred_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime, default=func.now())
    transaction_id = Column(String, nullable=True)

Base.metadata.create_all(engine)

# ==================== FSM STATES ====================
class ApplicationForm(StatesGroup):
    waiting_for_reddit = State()
    waiting_for_experience = State()
    waiting_for_skills = State()
    waiting_for_portfolio = State()
    waiting_for_why = State()

# ==================== BOT SETUP ====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ==================== HELPER FUNCTIONS ====================
def generate_referral_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def get_rank(conversions: int) -> str:
    if conversions >= 25:
        return "platinum"
    elif conversions >= 10:
        return "gold"
    elif conversions >= 5:
        return "silver"
    return "bronze"

def get_rank_percentage(rank: str) -> float:
    rank_map = {
        "bronze": 0.05,
        "silver": 0.06,
        "gold": 0.07,
        "platinum": 0.08
    }
    return rank_map.get(rank, 0.05)

# ==================== KEYBOARDS ====================
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Apply Now", callback_data="apply")],
        [InlineKeyboardButton(text="📊 My Status", callback_data="status")],
        [InlineKeyboardButton(text="📈 Dashboard", callback_data="dashboard")],
        [InlineKeyboardButton(text="🏆 Leaderboard", callback_data="leaderboard")],
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Pending Applications", callback_data="admin_pending")],
        [InlineKeyboardButton(text="📊 Overall Stats", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
    ])

# ==================== COMMANDS ====================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "👋 Welcome to Vega Referral Network.\n\n"
        "We're looking for skilled social engineers to join our team.\n"
        "You'll get paid for every qualified lead you bring in.\n\n"
        "🔹 Use /apply to start your application\n"
        "🔹 Use /status to check your application status\n"
        "🔹 Use /dashboard to see your stats (if approved)\n"
        "🔹 Use /refer to get your referral link\n\n"
        "Questions? Use /help"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "📖 **Available Commands**\n\n"
        "/start — Welcome and main menu\n"
        "/apply — Start the application process\n"
        "/status — Check your application status\n"
        "/dashboard — Your stats (approved referrers only)\n"
        "/refer — Get your referral link\n"
        "/leaderboard — Top referrers\n"
        "/help — This message\n\n"
        "**For Admins Only:**\n"
        "/admin — Admin panel"
    )
    await message.answer(help_text)

@dp.message(Command("apply"))
async def cmd_apply(message: types.Message, state: FSMContext):
    session = SessionLocal()
    existing = session.query(Applicant).filter_by(telegram_id=message.from_user.id).first()
    session.close()

    if existing:
        if existing.status == "pending":
            await message.answer("⏳ You already have a pending application. Please wait for review.")
        elif existing.status == "approved":
            await message.answer("✅ You're already approved! Use /dashboard to see your stats.")
        elif existing.status == "rejected":
            await message.answer("❌ Your application was rejected. You can reapply if you believe this was a mistake.")
        elif existing.status == "banned":
            await message.answer("🚫 You have been banned from this program.")
        return

    await message.answer(
        "📝 **Application — Step 1 of 5**\n\n"
        "What's your Reddit username? (or main platform you'll be working on)\n\n"
        "Format: /u/username or just the name."
    )
    await state.set_state(ApplicationForm.waiting_for_reddit)

@dp.message(ApplicationForm.waiting_for_reddit)
async def process_reddit(message: types.Message, state: FSMContext):
    await state.update_data(reddit_username=message.text.strip())
    await message.answer(
        "📝 **Step 2 of 5**\n\n"
        "How long have you been doing social engineering / outreach?\n\n"
        "Be honest. Examples: '1 year', '6 months', 'I've been doing this since 2021'."
    )
    await state.set_state(ApplicationForm.waiting_for_experience)

@dp.message(ApplicationForm.waiting_for_experience)
async def process_experience(message: types.Message, state: FSMContext):
    await state.update_data(experience=message.text.strip())
    await message.answer(
        "📝 **Step 3 of 5**\n\n"
        "What platforms are you most comfortable with?\n\n"
        "Example: Reddit, Twitter/X, Discord, Telegram, Facebook, etc."
    )
    await state.set_state(ApplicationForm.waiting_for_skills)

@dp.message(ApplicationForm.waiting_for_skills)
async def process_skills(message: types.Message, state: FSMContext):
    await state.update_data(skills=message.text.strip())
    await message.answer(
        "📝 **Step 4 of 5**\n\n"
        "What's your typical target portfolio size?\n\n"
        "Example: 5K-10K, 10K-50K, 50K+, or 'I work with whoever has at least 5K'."
    )
    await state.set_state(ApplicationForm.waiting_for_portfolio)

@dp.message(ApplicationForm.waiting_for_portfolio)
async def process_portfolio(message: types.Message, state: FSMContext):
    await state.update_data(portfolio_size=message.text.strip())
    await message.answer(
        "📝 **Step 5 of 5 (final)**\n\n"
        "Why should we work with you? (2-3 sentences)\n\n"
        "Tell us what makes you effective and why you'd be a good fit."
    )
    await state.set_state(ApplicationForm.waiting_for_why)

@dp.message(ApplicationForm.waiting_for_why)
async def process_why(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user = message.from_user

    session = SessionLocal()
    applicant = Applicant(
        telegram_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        reddit_username=data.get("reddit_username"),
        experience=data.get("experience"),
        skills=data.get("skills"),
        portfolio_size=data.get("portfolio_size"),
        why_you=message.text.strip(),
        status="pending"
    )
    session.add(applicant)
    session.commit()
    session.close()

    await state.clear()
    await message.answer(
        "✅ **Application submitted!**\n\n"
        "We'll review it within 24-48 hours.\n"
        "Use /status to check your status.\n\n"
        "If approved, you'll get access to your referral link and dashboard."
    )

    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📋 **New Application**\n\n"
                f"User: {user.first_name} (@{user.username})\n"
                f"Reddit: {data.get('reddit_username')}\n"
                f"Experience: {data.get('experience')}\n"
                f"Skills: {data.get('skills')}\n"
                f"Portfolio Target: {data.get('portfolio_size')}\n\n"
                f"Use /admin_apply to review."
            )
        except:
            pass

# ==================== STATUS COMMAND ====================
@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    session = SessionLocal()
    applicant = session.query(Applicant).filter_by(telegram_id=message.from_user.id).first()
    session.close()

    if not applicant:
        await message.answer("❌ You haven't applied yet. Use /apply to start.")
        return

    status_map = {
        "pending": "⏳ **Pending Review**\n\nYour application is being reviewed. We'll notify you when it's processed.",
        "approved": "✅ **Approved!**\n\nYou're now a referrer. Use /dashboard to see your stats and /refer to get your link.",
        "rejected": "❌ **Rejected**\n\nYour application was not approved. You can reapply if you believe this was a mistake.",
        "banned": "🚫 **Banned**\n\nYou have been banned from this program."
    }

    await message.answer(status_map.get(applicant.status, "Unknown status."))

# ==================== REFER COMMAND ====================
@dp.message(Command("refer"))
async def cmd_refer(message: types.Message):
    session = SessionLocal()
    applicant = session.query(Applicant).filter_by(telegram_id=message.from_user.id).first()
    
    if not applicant or applicant.status != "approved":
        session.close()
        await message.answer("❌ You need to be approved first. Use /apply to start.")
        return

    referrer = session.query(Referrer).filter_by(telegram_id=message.from_user.id).first()
    if not referrer:
        # Create referrer if doesn't exist
        code = generate_referral_code()
        link = f"{BASE_URL}?start=ref_{code}"
        referrer = Referrer(
            telegram_id=message.from_user.id,
            referral_code=code,
            referral_link=link
        )
        session.add(referrer)
        session.commit()

    session.close()

    await message.answer(
        f"🔗 **Your Referral Link**\n\n"
        f"`{referrer.referral_link}`\n\n"
        f"**Your Code:** `{referrer.referral_code}`\n\n"
        f"Share this link with people. When they join and onboard, you get paid.\n\n"
        f"📊 Current conversions: {referrer.total_conversions}\n"
        f"💰 Total earned: ${referrer.total_earned:.2f}\n"
        f"🏅 Rank: {referrer.rank.upper()}"
    )

# ==================== DASHBOARD COMMAND ====================
@dp.message(Command("dashboard"))
async def cmd_dashboard(message: types.Message):
    session = SessionLocal()
    applicant = session.query(Applicant).filter_by(telegram_id=message.from_user.id).first()
    
    if not applicant or applicant.status != "approved":
        session.close()
        await message.answer("❌ You need to be approved first. Use /apply to start.")
        return

    referrer = session.query(Referrer).filter_by(telegram_id=message.from_user.id).first()
    if not referrer:
        session.close()
        await message.answer("❌ No data found. Contact admin.")
        return

    referrals = session.query(Referral).filter_by(referrer_telegram_id=message.from_user.id).all()
    total_verified = len([r for r in referrals if r.status == "onboarded" or r.status == "paid"])
    total_paid = len([r for r in referrals if r.status == "paid"])

    session.close()

    rank_percent = get_rank_percentage(referrer.rank) * 100

    dashboard_text = (
        f"📊 **Your Dashboard**\n\n"
        f"🏅 Rank: {referrer.rank.upper()} ({rank_percent:.0f}% of mentor's cut)\n"
        f"🔗 Referral Code: `{referrer.referral_code}`\n"
        f"📥 Total Referrals: {len(referrals)}\n"
        f"✅ Verified Conversions: {total_verified}\n"
        f"💰 Paid Conversions: {total_paid}\n"
        f"💵 Total Earned: ${referrer.total_earned:.2f}\n"
        f"⏳ Pending Earnings: ${referrer.pending_earned:.2f}\n\n"
        f"Use /refer to get your link.\n"
        f"Use /leaderboard to see top performers."
    )

    await message.answer(dashboard_text)

# ==================== LEADERBOARD COMMAND ====================
@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: types.Message):
    session = SessionLocal()
    top_referrers = session.query(Referrer).order_by(Referrer.total_conversions.desc()).limit(10).all()
    session.close()

    if not top_referrers:
        await message.answer("🏆 No referrers yet. Be the first!")
        return

    leaderboard_text = "🏆 **Leaderboard**\n\n"
    for idx, ref in enumerate(top_referrers, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"{idx}.")
        # Get username
        try:
            user = await bot.get_chat(ref.telegram_id)
            name = user.first_name or f"User_{ref.telegram_id}"
        except:
            name = f"User_{ref.telegram_id}"
        leaderboard_text += f"{medal} {name} — {ref.total_conversions} conversions (${ref.total_earned:.2f})\n"

    await message.answer(leaderboard_text)

# ==================== ADMIN COMMANDS ====================
@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Unauthorized.")
        return
    
    await message.answer(
        "🛠 **Admin Panel**\n\n"
        "Select an option:",
        reply_markup=get_admin_keyboard()
    )

@dp.callback_query(F.data == "admin_pending")
async def admin_pending(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Unauthorized.", show_alert=True)
        return

    session = SessionLocal()
    pending = session.query(Applicant).filter_by(status="pending").all()
    session.close()

    if not pending:
        await callback.message.answer("📋 No pending applications.")
        await callback.answer()
        return

    for app in pending[:5]:  # Show 5 at a time
        text = (
            f"📋 **Application #{app.id}**\n\n"
            f"User: {app.first_name} (@{app.username})\n"
            f"Reddit: {app.reddit_username}\n"
            f"Experience: {app.experience}\n"
            f"Skills: {app.skills}\n"
            f"Portfolio Target: {app.portfolio_size}\n"
            f"Why: {app.why_you}\n"
            f"Applied: {app.applied_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Use:\n"
            f"/admin_approve {app.id} — Approve\n"
            f"/admin_reject {app.id} — Reject"
        )
        await callback.message.answer(text)

    await callback.answer()

@dp.message(Command("admin_approve"))
async def admin_approve(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    try:
        app_id = int(message.text.split()[1])
    except:
        await message.answer("❌ Usage: /admin_approve [id]")
        return

    session = SessionLocal()
    applicant = session.query(Applicant).filter_by(id=app_id).first()
    if not applicant:
        session.close()
        await message.answer("❌ Applicant not found.")
        return

    # Update applicant
    applicant.status = "approved"
    applicant.approved_at = datetime.now()
    applicant.approved_by = message.from_user.id
    session.commit()

    # Create referrer
    code = generate_referral_code()
    link = f"{BASE_URL}?start=ref_{code}"
    referrer = Referrer(
        telegram_id=applicant.telegram_id,
        referral_code=code,
        referral_link=link
    )
    session.add(referrer)
    session.commit()
    session.close()

    await message.answer(f"✅ Applicant #{app_id} approved. Referrer created.")

    # Notify user
    try:
        await bot.send_message(
            applicant.telegram_id,
            "✅ **Congratulations! Your application has been approved.**\n\n"
            "You now have access to the referral program.\n\n"
            "🔗 Use /refer to get your unique link.\n"
            "📊 Use /dashboard to track your stats.\n"
            "📖 Use /help if you need anything.\n\n"
            "Let's get to work."
        )
    except:
        pass

@dp.message(Command("admin_reject"))
async def admin_reject(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    try:
        app_id = int(message.text.split()[1])
    except:
        await message.answer("❌ Usage: /admin_reject [id]")
        return

    session = SessionLocal()
    applicant = session.query(Applicant).filter_by(id=app_id).first()
    if not applicant:
        session.close()
        await message.answer("❌ Applicant not found.")
        return

    applicant.status = "rejected"
    session.commit()
    session.close()

    await message.answer(f"❌ Applicant #{app_id} rejected.")

    try:
        await bot.send_message(
            applicant.telegram_id,
            "❌ Your application was not approved. Thank you for your interest."
        )
    except:
        pass

@dp.message(Command("admin_stats"))
async def admin_stats(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    session = SessionLocal()
    total_applicants = session.query(Applicant).count()
    pending_applicants = session.query(Applicant).filter_by(status="pending").count()
    approved_applicants = session.query(Applicant).filter_by(status="approved").count()
    total_referrals = session.query(Referral).count()
    total_onboarded = session.query(Referral).filter_by(status="onboarded").count()
    total_paid = session.query(Referral).filter_by(status="paid").count()
    total_earned = session.query(Payment).with_entities(func.sum(Payment.amount)).scalar() or 0.0
    session.close()

    stats_text = (
        f"📊 **Bot Statistics**\n\n"
        f"👤 Applicants: {total_applicants}\n"
        f"⏳ Pending: {pending_applicants}\n"
        f"✅ Approved: {approved_applicants}\n"
        f"🔗 Total Referrals: {total_referrals}\n"
        f"📥 Onboarded: {total_onboarded}\n"
        f"💰 Paid Conversions: {total_paid}\n"
        f"💵 Total Paid Out: ${total_earned:.2f}"
    )

    await message.answer(stats_text)

@dp.message(Command("admin_broadcast"))
async def admin_broadcast(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    # Usage: /admin_broadcast Your message here
    text = message.text.replace("/admin_broadcast", "").strip()
    if not text:
        await message.answer("❌ Usage: /admin_broadcast [your message]")
        return

    session = SessionLocal()
    referrers = session.query(Referrer).all()
    session.close()

    sent = 0
    for ref in referrers:
        try:
            await bot.send_message(ref.telegram_id, f"📢 **Broadcast**\n\n{text}")
            sent += 1
            await asyncio.sleep(0.1)  # avoid rate limit
        except:
            pass

    await message.answer(f"✅ Broadcast sent to {sent} referrers.")

# ==================== CALLBACKS ====================
@dp.callback_query(F.data == "apply")
async def callback_apply(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await cmd_apply(callback.message, state)

@dp.callback_query(F.data == "status")
async def callback_status(callback: types.CallbackQuery):
    await callback.answer()
    await cmd_status(callback.message)

@dp.callback_query(F.data == "dashboard")
async def callback_dashboard(callback: types.CallbackQuery):
    await callback.answer()
    await cmd_dashboard(callback.message)

@dp.callback_query(F.data == "leaderboard")
async def callback_leaderboard(callback: types.CallbackQuery):
    await callback.answer()
    await cmd_leaderboard(callback.message)

@dp.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: types.CallbackQuery):
    await callback.answer()
    await admin_stats(callback.message)

@dp.callback_query(F.data == "admin_broadcast")
async def callback_admin_broadcast(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("📢 Enter your broadcast message:\n/admin_broadcast [your message]")

# ==================== MAIN ====================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())