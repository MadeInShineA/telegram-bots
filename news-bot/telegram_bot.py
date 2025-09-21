#!/usr/bin/env python3
"""
Telegram News Bot - Python 3.12 Compatible
A public telegram bot for personalized news delivery with AI summaries.
"""

import asyncio
import logging
import requests
import sys
from datetime import datetime, timedelta
from typing import Dict, List
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

# Scheduler imports removed for simplicity
import sqlite3
import os
from dotenv import load_dotenv

# Import our news processing functions
from news_processor import (
    send_news_category,
    init_database,
    cleanup_old_messages,
    get_sent_messages_list,
    record_statistics,
    register_user,
    get_user_preferences,
    update_user_preferences,
    get_user_stats,
)

from news_scheduler import NewsScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("telegram_bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# News categories configuration
NEWS_CATEGORIES = {
    "technology": {"emoji": "💻", "description": "Latest technology news and updates"},
    "science": {"emoji": "🔬", "description": "Scientific discoveries and research"},
    "sports": {"emoji": "⚽", "description": "Sports news and highlights"},
    "business": {"emoji": "💼", "description": "Business and financial news"},
}


class NewsTelegramBot:
    def __init__(self):
        self.news_categories_dict = None
        self.bot_token = None
        self.bot_chatID = None
        self.news_data_key = None
        self.textgear_api_key = None
        self.tags_to_avoid = [
            "style",
            "script",
            "head",
            "title",
            "meta",
            "figcaption",
            "[document]",
            "sub",
        ]
        # Scheduler removed for simplicity
        self.application = None
        self.scheduler_manager = None

    def setup_config(self):
        """Setup configuration from environment variables."""
        load_dotenv()

        # Only require essential keys for DM-based bot
        required_vars = ["BOT_TOKEN", "NEWS_DATA_KEY", "TEXT_GEAR_KEY"]
        missing_vars = []
        for var in required_vars:
            if not os.environ.get(var):
                missing_vars.append(var)

        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

        self.bot_token = os.environ.get("BOT_TOKEN")
        self.news_data_key = os.environ.get("NEWS_DATA_KEY")
        self.textgear_api_key = os.environ.get("TEXT_GEAR_KEY")

        # News categories configuration (no thread IDs needed for DM)
        self.news_categories_dict = {
            "technology": {
                "news_sources": {
                    "sciencealert": {
                        "source_name": "Science Alert",
                        "news_container": {"div": "post-content"},
                        "classes_to_avoid": [],
                    },
                    "phys": {
                        "source_name": "Phys.org",
                        "news_container": {"div": "article-main"},
                        "classes_to_avoid": [
                            "article-main__more",
                            "d-inline-block",
                            "d-none",
                        ],
                    },
                    "wired": {
                        "source_name": "Wired",
                        "news_container": {"div": "body__inner-container"},
                        "classes_to_avoid": [],
                    },
                    "techcrunch": {
                        "source_name": "TechCrunch",
                        "news_container": {"div": "article-content"},
                        "classes_to_avoid": [
                            "embed",
                            "wp-embedded-content",
                            "piano-inline-promo",
                            "tp-container-inner",
                        ],
                    },
                }
            },
            "science": {
                "news_sources": {
                    "sciencealert": {
                        "source_name": "Science Alert",
                        "news_container": {"div": "post-content"},
                        "classes_to_avoid": [],
                    },
                    "phys": {
                        "source_name": "Phys.org",
                        "news_container": {"div": "article-main"},
                        "classes_to_avoid": [
                            "article-main__more",
                            "d-inline-block",
                            "d-none",
                        ],
                    },
                    "wired": {
                        "source_name": "Wired",
                        "news_container": {"div": "body__inner-container"},
                        "classes_to_avoid": [],
                    },
                    "techcrunch": {
                        "source_name": "TechCrunch",
                        "news_container": {"div": "article-content"},
                        "classes_to_avoid": [
                            "embed",
                            "wp-embedded-content",
                            "piano-inline-promo",
                            "tp-container-inner",
                        ],
                    },
                }
            },
            "sports": {
                "news_sources": {
                    "espn": {
                        "source_name": "ESPN",
                        "news_container": {"div": "article-body"},
                        "classes_to_avoid": [
                            "article-meta",
                            "content-reactions",
                            "editorial",
                        ],
                    },
                }
            },
            "business": {
                "news_sources": {
                    "cnbc": {
                        "source_name": "CNBC",
                        "news_container": {"div": "ArticleBody-articleBody"},
                        "classes_to_avoid": [
                            "RelatedContent-relatedContent",
                            "RelatedQuotes-relatedQuotes",
                            "InlineImage-imageEmbed",
                            "InlineImage-wrapper",
                            "QuoteInBody-inlineButton",
                        ],
                    },
                }
            },
        }

    async def setup_scheduler(self):
        """Initialize the news scheduler."""
        try:
            self.scheduler_manager = NewsScheduler(self)
            success = await self.scheduler_manager.start()
            if success:
                logger.info("News scheduler initialized successfully")
            else:
                logger.error("Failed to initialize news scheduler")
        except Exception as e:
            logger.error(f"Error setting up scheduler: {e}")

    async def scheduled_users_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /scheduled command to see active schedules."""
        if not self.scheduler_manager:
            await update.message.reply_text("❌ Scheduler not initialized")
            return

        try:
            scheduled_users = self.scheduler_manager.get_scheduled_users()

            if not scheduled_users:
                await update.message.reply_text(
                    "📅 No users currently scheduled for automatic news delivery"
                )
                return

            schedule_text = (
                f"📅 **Active Schedules** ({len(scheduled_users)} users)\n\n"
            )

            for user_info in scheduled_users[:10]:  # Limit to 10 for display
                schedule_text += f"👤 User {user_info['user_id']}\n"
                schedule_text += f"⏰ Next: {user_info['next_run']}\n"
                schedule_text += f"🌍 TZ: {user_info['timezone']}\n\n"

            if len(scheduled_users) > 10:
                schedule_text += f"... and {len(scheduled_users) - 10} more users"

            await update.message.reply_text(
                schedule_text, parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error(f"Error in scheduled users command: {e}")
            await update.message.reply_text("❌ Error getting scheduled users")

    async def ensure_user_registered(self, update: Update) -> None:
        """Ensure user is registered in database."""
        user = update.effective_user
        register_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )

    async def start_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /start command."""
        await self.ensure_user_registered(update)

        user = update.effective_user
        user_prefs = get_user_preferences(user.id)

        welcome_text = f"""
👋 **Hi {user.first_name}!**

Ready for some news? Just pick what you're interested in:
        """

        # Create simple action-focused keyboard
        keyboard = [
            [InlineKeyboardButton("📰 Get News", callback_data="show_news_menu")],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                InlineKeyboardButton("📊 Dashboard", callback_data="dashboard_refresh"),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    async def help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /help command."""
        await self.ensure_user_registered(update)

        help_text = """
🤖 **News Bot Help**

**Commands:**
• `/start` - Show welcome message and main menu
• `/news` - Show news category selection
• `/news [category]` - Get news for specific category
• `/status` - Show bot health and statistics
• `/sources` - List all news sources
• `/dashboard` - View analytics and metrics
• `/schedule` - Manage automatic news scheduling
• `/help` - Show this help message

**Features:**
✅ Real-time news from multiple sources
✅ AI-powered article summaries
✅ Duplicate detection
✅ Category-based organization
✅ Interactive buttons and menus
✅ Analytics dashboard with metrics
✅ Automatic scheduling (daily/custom times)

**Tips:**
💡 Use buttons for easier navigation
💡 Check `/dashboard` for detailed analytics
💡 Set up `/schedule add 08:00 technology` for daily news
💡 Each category has dedicated threads
        """

        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def news_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self.ensure_user_registered(update)

        if context.args:
            category = context.args[0].lower()
            if category in NEWS_CATEGORIES:
                await self.fetch_news_for_category(update, category)
            else:
                await update.message.reply_text(
                    f"❌ Unknown category: {category}\n"
                    f"Available categories: {', '.join(NEWS_CATEGORIES.keys())}"
                )
            return

        # No args → send the same as "📰 Get News" button
        await self.show_news_menu(update)

    async def show_news_menu(self, update: Update) -> None:
        """Show news category selection menu."""
        text = "📰 **Select a news category:**"

        keyboard = []
        for category, data in NEWS_CATEGORIES.items():
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{data['emoji']} {category.title()}",
                        callback_data=f"news_{category}",
                    )
                ]
            )

        keyboard.append(
            [InlineKeyboardButton("🔄 All Categories", callback_data="news_all")]
        )

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    async def status_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /status command."""
        try:
            await self.ensure_user_registered(update)

            # Get user's timezone preference
            user_prefs = get_user_preferences(update.effective_user.id)
            user_timezone = user_prefs.get("timezone", "UTC")

            # Get current time in user's timezone
            try:
                user_tz = pytz.timezone(user_timezone)
                current_time = datetime.now(user_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
            except:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

            sent_messages = get_sent_messages_list()

            status_text = f"""
📊 **Bot Status Report**

🕒 **Current Time:** {current_time}
📨 **Messages Sent Today:** {len([msg for msg in sent_messages if msg])}
💾 **Database:** ✅ Connected
🔗 **APIs:** ✅ Configured

**News Categories:**
{chr(10).join([f"{data['emoji']} {cat.title()}: Available" for cat, data in NEWS_CATEGORIES.items()])}

**Recent Activity:**
Last {min(5, len(sent_messages))} sent articles tracked in database.

Use `/sources` to see configured news sources.
            """

            await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Error in status command: {e}")
            await update.message.reply_text("❌ Error getting bot status")

    async def sources_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /sources command."""
        try:
            sources_text = "📰 **News Sources by Category:**\n\n"

            for category, config in self.news_categories_dict.items():
                emoji = NEWS_CATEGORIES[category]["emoji"]
                sources_text += f"{emoji} **{category.title()}:**\n"

                for source_key, source_info in config["news_sources"].items():
                    sources_text += f"  • {source_info['source_name']}\n"

                sources_text += "\n"

            sources_text += "💡 **Note:** All sources are fetched via NewsData.io API"

            await update.message.reply_text(sources_text, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Error in sources command: {e}")
            await update.message.reply_text("❌ Error getting sources list")

    async def dashboard_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /dashboard command - show analytics and metrics."""
        await self.ensure_user_registered(update)

        try:
            dashboard_text = await self.get_dashboard_data()

            # Create inline keyboard for dashboard actions
            keyboard = [
                [
                    InlineKeyboardButton(
                        "📊 Detailed Stats", callback_data="dashboard_detailed"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📈 Last 7 Days", callback_data="dashboard_week"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "👥 User Stats", callback_data="dashboard_users"
                    )
                ],
                [InlineKeyboardButton("🔄 Refresh", callback_data="dashboard_refresh")],
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                dashboard_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Error in dashboard command: {e}")
            await update.message.reply_text("❌ Error loading dashboard")

    async def schedule_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /schedule command for setting up automatic news delivery."""
        await self.ensure_user_registered(update)

        if not context.args:
            # Show current schedules and help
            current_jobs = self.get_scheduled_jobs()

            schedule_text = "⏰ **News Scheduling**\n\n"

            if current_jobs:
                schedule_text += "**Active Schedules:**\n"
                for job in current_jobs:
                    status = "✅" if job["is_active"] else "❌"
                    schedule_text += (
                        f"{status} {job['job_name']} - {job['schedule_time']}\n"
                    )
                schedule_text += "\n"

            schedule_text += """**Usage:**
• `/schedule add 08:00 technology` - Add daily tech news at 8 AM
• `/schedule add 18:00 all` - Add all categories at 6 PM
• `/schedule list` - Show all scheduled jobs
• `/schedule remove [job_name]` - Remove a scheduled job
• `/schedule toggle [job_name]` - Enable/disable a job

**Time format:** HH:MM (24-hour format)
**Categories:** technology, science, sports, business, all
            """

            await update.message.reply_text(
                schedule_text, parse_mode=ParseMode.MARKDOWN
            )
            return

        action = context.args[0].lower()

        if action == "add" and len(context.args) >= 3:
            time_str = context.args[1]
            category = context.args[2].lower()

            # Validate time format
            try:
                hour, minute = map(int, time_str.split(":"))
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError("Invalid time")
            except:
                await update.message.reply_text(
                    "❌ Invalid time format. Use HH:MM (24-hour)"
                )
                return

            # Validate category
            valid_categories = list(NEWS_CATEGORIES.keys()) + ["all"]
            if category not in valid_categories:
                await update.message.reply_text(
                    f"❌ Invalid category. Use: {', '.join(valid_categories)}"
                )
                return

            # Add the scheduled job
            success = await self.add_scheduled_job(time_str, category)
            if success:
                await update.message.reply_text(
                    f"✅ Scheduled {category} news for {time_str} daily"
                )
            else:
                await update.message.reply_text("❌ Failed to add schedule")

        elif action == "list":
            jobs = self.get_scheduled_jobs()
            if not jobs:
                await update.message.reply_text("📅 No scheduled jobs found")
                return

            jobs_text = "📅 **Scheduled Jobs:**\n\n"
            for job in jobs:
                status = "✅ Active" if job["is_active"] else "❌ Inactive"
                jobs_text += f"**{job['job_name']}**\n"
                jobs_text += f"⏰ Time: {job['schedule_time']}\n"
                jobs_text += f"📂 Category: {job['category']}\n"
                jobs_text += f"🔄 Status: {status}\n"
                if job["last_run"]:
                    jobs_text += f"🕐 Last run: {job['last_run']}\n"
                jobs_text += "\n"

            await update.message.reply_text(jobs_text, parse_mode=ParseMode.MARKDOWN)

        elif action == "remove" and len(context.args) >= 2:
            job_name = " ".join(context.args[1:])
            success = self.remove_scheduled_job(job_name)
            if success:
                await update.message.reply_text(f"✅ Removed scheduled job: {job_name}")
            else:
                await update.message.reply_text(f"❌ Job not found: {job_name}")

        elif action == "toggle" and len(context.args) >= 2:
            job_name = " ".join(context.args[1:])
            success = self.toggle_scheduled_job(job_name)
            if success:
                await update.message.reply_text(f"✅ Toggled job: {job_name}")
            else:
                await update.message.reply_text(f"❌ Job not found: {job_name}")
        else:
            await update.message.reply_text(
                "❌ Invalid schedule command. Use `/schedule` for help."
            )

    async def settings_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle /settings command for user preferences."""
        await self.ensure_user_registered(update)

        user_id = update.effective_user.id
        user_prefs = get_user_preferences(user_id)

        settings_text = f"""⚙️ **Your Settings**

📂 **Subscribed Categories:**
{", ".join([cat.title() for cat in user_prefs.get("subscribed_categories", [])]) or "None"}

⏰ **Preferred Time:**
{user_prefs.get("preferred_time") or "Not set"}

📊 **Daily Limit:**
{user_prefs.get("daily_limit", 5)} articles per category

🔔 **Notifications:**
{"✅ Enabled" if user_prefs.get("notifications", True) else "❌ Disabled"}

🌐 **Language:**
{user_prefs.get("language", "en").upper()}

**Commands to customize:**
• `/settings categories` - Manage subscriptions
• `/settings time HH:MM` - Set preferred time
• `/settings limit N` - Set daily article limit
• `/settings notifications on/off` - Toggle notifications
        """

        keyboard = [
            [
                InlineKeyboardButton(
                    "📂 Categories", callback_data="settings_categories"
                )
            ],
            [InlineKeyboardButton("⏰ Schedule Time", callback_data="settings_time")],
            [InlineKeyboardButton("📊 Daily Limit", callback_data="settings_limit")],
            [
                InlineKeyboardButton(
                    "🔔 Notifications", callback_data="settings_notifications"
                )
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        if not context.args:
            await update.message.reply_text(
                settings_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )
            return

        # Handle settings commands
        setting = context.args[0].lower()

        if setting == "categories" and len(context.args) >= 2:
            # Update subscribed categories
            action = context.args[1].lower()
            if action == "all":
                categories = list(NEWS_CATEGORIES.keys())
                update_user_preferences(user_id, subscribed_categories=categories)
                await update.message.reply_text("✅ Subscribed to all categories!")
            elif action == "none":
                update_user_preferences(user_id, subscribed_categories=[])
                await update.message.reply_text("✅ Unsubscribed from all categories!")
            elif action in NEWS_CATEGORIES:
                current_cats = user_prefs.get("subscribed_categories", [])
                if action in current_cats:
                    current_cats.remove(action)
                    await update.message.reply_text(f"✅ Unsubscribed from {action}!")
                else:
                    current_cats.append(action)
                    await update.message.reply_text(f"✅ Subscribed to {action}!")
                update_user_preferences(user_id, subscribed_categories=current_cats)
            else:
                await update.message.reply_text(
                    "❌ Invalid category. Use: technology, science, sports, business, all, none"
                )

        elif setting == "time" and len(context.args) >= 2:
            time_str = context.args[1]
            try:
                hour, minute = map(int, time_str.split(":"))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    update_user_preferences(user_id, preferred_time=time_str)
                    await update.message.reply_text(
                        f"✅ Preferred time set to {time_str}!"
                    )
                else:
                    raise ValueError("Invalid time")
            except:
                await update.message.reply_text(
                    "❌ Invalid time format. Use HH:MM (24-hour)"
                )

        elif setting == "limit" and len(context.args) >= 2:
            try:
                limit = int(context.args[1])
                if 1 <= limit <= 20:
                    update_user_preferences(user_id, daily_limit=limit)
                    await update.message.reply_text(
                        f"✅ Daily limit set to {limit} articles!"
                    )
                else:
                    raise ValueError("Invalid limit")
            except:
                await update.message.reply_text(
                    "❌ Invalid limit. Use a number between 1-20"
                )

        elif setting == "notifications" and len(context.args) >= 2:
            toggle = context.args[1].lower()
            if toggle in ["on", "true", "yes", "1"]:
                update_user_preferences(user_id, notifications=True)
                await update.message.reply_text("✅ Notifications enabled!")
            elif toggle in ["off", "false", "no", "0"]:
                update_user_preferences(user_id, notifications=False)
                await update.message.reply_text("✅ Notifications disabled!")
            else:
                await update.message.reply_text(
                    "❌ Use 'on' or 'off' for notifications"
                )

        else:
            await update.message.reply_text(
                "❌ Invalid settings command. Use `/settings` for help."
            )

    # Database helper methods for dashboard and scheduling
    async def get_dashboard_data(self) -> str:
        """Get dashboard analytics data."""
        try:
            with sqlite3.connect("news_bot.db") as conn:
                cursor = conn.cursor()

                # Get today's stats
                cursor.execute("""
                    SELECT COUNT(*) as total_sent,
                           COUNT(DISTINCT category) as categories_used,
                           COUNT(DISTINCT source) as sources_used
                    FROM sent_messages
                    WHERE DATE(sent_at) = DATE('now')
                """)
                today_stats = cursor.fetchone()

                # Get total stats
                cursor.execute("""
                    SELECT COUNT(*) as total_messages,
                           COUNT(DISTINCT category) as total_categories,
                           MIN(sent_at) as first_message
                    FROM sent_messages
                """)
                total_stats = cursor.fetchone()

                # Get category breakdown for today
                cursor.execute("""
                    SELECT category, COUNT(*) as count
                    FROM sent_messages
                    WHERE DATE(sent_at) = DATE('now') AND category IS NOT NULL
                    GROUP BY category
                    ORDER BY count DESC
                """)
                category_stats = cursor.fetchall()

                # Get scheduled jobs count
                cursor.execute(
                    "SELECT COUNT(*) FROM scheduled_jobs WHERE is_active = 1"
                )
                active_jobs = cursor.fetchone()[0]

                dashboard_text = f"""📊 **News Bot Dashboard**

🗓️ **Today's Activity:**
• 📨 Messages sent: {today_stats[0]}
• 📂 Categories used: {today_stats[1]}
• 🌐 Sources active: {today_stats[2]}

📈 **Overall Statistics:**
• 📊 Total messages: {total_stats[0]}
• ⏰ Active schedules: {active_jobs}
• 🚀 Bot running since: {total_stats[2][:10] if total_stats[2] else "Unknown"}

📂 **Today's Category Breakdown:**"""

                if category_stats:
                    for category, count in category_stats:
                        emoji = NEWS_CATEGORIES.get(category, {}).get("emoji", "📰")
                        dashboard_text += f"\n{emoji} {category}: {count} articles"
                else:
                    dashboard_text += "\nNo articles sent today yet."

                return dashboard_text

        except Exception as e:
            logger.error(f"Error getting dashboard data: {e}")
            return "❌ Error loading dashboard data"

    def get_scheduled_jobs(self) -> List[Dict]:
        """Get all scheduled jobs from database."""
        try:
            with sqlite3.connect("news_bot.db") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT job_name, category, schedule_time, is_active, last_run
                    FROM scheduled_jobs
                    ORDER BY schedule_time
                """)

                jobs = []
                for row in cursor.fetchall():
                    jobs.append(
                        {
                            "job_name": row[0],
                            "category": row[1],
                            "schedule_time": row[2],
                            "is_active": bool(row[3]),
                            "last_run": row[4],
                        }
                    )
                return jobs

        except Exception as e:
            logger.error(f"Error getting scheduled jobs: {e}")
            return []

    async def add_scheduled_job(self, time_str: str, category: str) -> bool:
        """Add a new scheduled job."""
        try:
            job_name = f"{category}_news_{time_str.replace(':', '')}"

            # Add to database
            with sqlite3.connect("news_bot.db") as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO scheduled_jobs
                    (job_name, category, schedule_time, is_active)
                    VALUES (?, ?, ?, 1)
                """,
                    (job_name, category, time_str),
                )

            logger.info(f"Added scheduled job: {job_name}")
            return True

        except Exception as e:
            logger.error(f"Error adding scheduled job: {e}")
            return False

    def remove_scheduled_job(self, job_name: str) -> bool:
        """Remove a scheduled job."""
        try:
            # Remove from database
            with sqlite3.connect("news_bot.db") as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM scheduled_jobs WHERE job_name = ?", (job_name,)
                )
                if cursor.rowcount == 0:
                    return False

            logger.info(f"Removed scheduled job: {job_name}")
            return True

        except Exception as e:
            logger.error(f"Error removing scheduled job: {e}")
            return False

    def toggle_scheduled_job(self, job_name: str) -> bool:
        """Toggle a scheduled job active/inactive."""
        try:
            with sqlite3.connect("news_bot.db") as conn:
                cursor = conn.cursor()

                # Get current status
                cursor.execute(
                    "SELECT is_active FROM scheduled_jobs WHERE job_name = ?",
                    (job_name,),
                )
                result = cursor.fetchone()
                if not result:
                    return False

                new_status = not bool(result[0])

                # Update database
                cursor.execute(
                    "UPDATE scheduled_jobs SET is_active = ? WHERE job_name = ?",
                    (new_status, job_name),
                )

            return True

        except Exception as e:
            logger.error(f"Error toggling scheduled job: {e}")
            return False

    async def fetch_news_for_category(self, update: Update, category: str) -> None:
        """Fetch and send news for a specific category directly to user's DM."""
        try:
            user_id = update.effective_user.id

            # Send "fetching news" message
            status_msg = await update.message.reply_text(
                f"🔄 Fetching {NEWS_CATEGORIES[category]['emoji']} {category} news..."
            )

            # Get category configuration
            config = self.news_categories_dict[category]
            news_sources = config["news_sources"]

            # Fetch news using our DM-specific function
            articles_sent = await self.send_news_to_dm(user_id, category, news_sources)

            # Update status message
            if articles_sent > 0:
                await status_msg.edit_text(
                    f"✅ {NEWS_CATEGORIES[category]['emoji']} {category.title()} news: {articles_sent} articles sent!"
                )
            else:
                await status_msg.edit_text(
                    f"📰 {NEWS_CATEGORIES[category]['emoji']} No new {category} news available right now."
                )

        except Exception as e:
            logger.error(f"Error fetching news for {category}: {e}")
            await update.message.reply_text(
                f"❌ Error fetching {category} news: {str(e)}"
            )

    async def send_news_to_dm(
        self, user_id: int, category: str, news_sources: Dict
    ) -> int:
        """Send news articles directly to user's DM with user-based tracking and limits."""
        try:
            logger.info(f"Sending {category} news to user {user_id}")

            # Import the functions we need from news_processor
            from news_processor import (
                extract_content,
                summarize_text,
                is_message_sent,
                record_sent_message,
            )

            # Get user preferences to check their limit
            user_prefs = get_user_preferences(user_id)
            daily_limit = user_prefs.get("daily_limit", 5)

            # Fetch news from API
            articles = []
            for news_source in news_sources.keys():
                try:
                    url = f"https://newsdata.io/api/1/news?apikey={self.news_data_key}&category={category}&language=en&domain={news_source}"

                    response = requests.get(url, timeout=30)
                    response.raise_for_status()
                    response_data = response.json()

                    if "results" in response_data:
                        for article in response_data["results"]:
                            if article.get("link") and article.get("title"):
                                articles.append((article, news_source))

                except Exception as e:
                    logger.error(f"Error fetching from {news_source}: {e}")
                    continue

            # Filter out already sent messages FOR THIS SPECIFIC USER
            new_articles = [
                (article, source)
                for article, source in articles
                if not is_message_sent(article.get("title"), user_id)
            ]

            if not new_articles:
                return 0

            # Get user's timezone for header
            user_timezone = user_prefs.get("timezone", "UTC")
            try:
                user_tz = pytz.timezone(user_timezone)
                today = datetime.now(user_tz).strftime("%B %d, %Y")
            except:
                today = datetime.now().strftime("%B %d, %Y")

            # Send category header
            header_msg = (
                f"📰 **{today}'s {category.title()} News**\n━━━━━━━━━━━━━━━━━━━━━━"
            )
            await self.application.bot.send_message(
                chat_id=user_id, text=header_msg, parse_mode=ParseMode.MARKDOWN
            )

            articles_sent = 0
            max_articles = min(daily_limit, len(new_articles))  # Respect user's limit

            # Send multiple articles up to the user's limit
            for article, source_key in new_articles[:max_articles]:
                try:
                    # Extract content
                    source_config = news_sources[source_key]
                    news_container = source_config["news_container"]
                    classes_to_avoid = source_config["classes_to_avoid"]

                    content = extract_content(
                        news_container,
                        classes_to_avoid,
                        self.tags_to_avoid,
                        article["link"],
                        source_key,
                    )

                    if not content:
                        continue

                    # Summarize content
                    summary = summarize_text(self.textgear_api_key, content)
                    if not summary:
                        continue

                    # Create individual article message
                    source_name = source_config["source_name"]
                    message = f"**{article['title']}**\n\n"
                    message += f"📝 {summary}\n\n"
                    message += f"🔗 [Read full article]({article['link']})\n"
                    message += f"📰 *Source: {source_name}*"

                    # Send the article
                    await self.application.bot.send_message(
                        chat_id=user_id,
                        text=message,
                        parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=False,
                    )

                    # Record sent message FOR THIS SPECIFIC USER
                    record_sent_message(
                        article["title"], article["link"], category, source_key, user_id
                    )
                    articles_sent += 1

                    # Small delay between articles
                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error(
                        f"Error processing article {article.get('title')}: {e}"
                    )
                    continue

            # Send footer with count
            if articles_sent > 0:
                footer_msg = f"━━━━━━━━━━━━━━━━━━━━━━\n📊 Sent {articles_sent} of {len(new_articles)} available articles\n💡 *Change your limit in /settings*"
                await self.application.bot.send_message(
                    chat_id=user_id, text=footer_msg, parse_mode=ParseMode.MARKDOWN
                )

            logger.info(f"Sent {articles_sent} {category} articles to user {user_id}")
            return articles_sent

        except Exception as e:
            logger.error(f"Error sending news to DM: {e}")
            return 0

    async def button_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle button callbacks."""
        query = update.callback_query
        await query.answer()

        callback_data = query.data

        if callback_data == "show_news_menu":
            # Show the news category selection menu
            text = "📰 **What kind of news would you like?**"

            keyboard = []
            for category, data in NEWS_CATEGORIES.items():
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{data['emoji']} {category.title()}",
                            callback_data=f"news_{category}",
                        )
                    ]
                )

            keyboard.append(
                [InlineKeyboardButton("🔄 All Categories", callback_data="news_all")]
            )
            keyboard.append(
                [InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")]
            )

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )

        elif callback_data.startswith("news_"):
            category = callback_data.replace("news_", "")

            if category == "all":
                # Fetch all categories
                await query.edit_message_text("🔄 Fetching news for all categories...")

                user_id = query.from_user.id
                total_articles = 0

                for cat in NEWS_CATEGORIES.keys():
                    try:
                        config = self.news_categories_dict[cat]
                        news_sources = config["news_sources"]

                        articles_sent = await self.send_news_to_dm(
                            user_id, cat, news_sources
                        )
                        total_articles += articles_sent

                        # Small delay between categories
                        await asyncio.sleep(1)

                    except Exception as e:
                        logger.error(f"Error processing {cat}: {e}")

                await query.edit_message_text(
                    f"✅ All categories processed! {total_articles} articles sent."
                )

            elif category in NEWS_CATEGORIES:
                # Fetch specific category
                await query.edit_message_text(
                    f"🔄 Fetching {NEWS_CATEGORIES[category]['emoji']} {category} news..."
                )

                try:
                    user_id = query.from_user.id
                    config = self.news_categories_dict[category]
                    news_sources = config["news_sources"]

                    # Send news to user's DM
                    articles_sent = await self.send_news_to_dm(
                        user_id, category, news_sources
                    )

                    if articles_sent > 0:
                        await query.edit_message_text(
                            f"✅ {NEWS_CATEGORIES[category]['emoji']} {category.title()} news: {articles_sent} articles sent!"
                        )
                    else:
                        await query.edit_message_text(
                            f"📰 {NEWS_CATEGORIES[category]['emoji']} No new {category} news available."
                        )

                except Exception as e:
                    logger.error(f"Error fetching {category} news: {e}")
                    await query.edit_message_text(f"❌ Error fetching {category} news")

        elif callback_data == "status":
            # Show status with user's timezone
            try:
                user_prefs = get_user_preferences(query.from_user.id)
                user_timezone = user_prefs.get("timezone", "UTC")

                # Get current time in user's timezone
                try:
                    user_tz = pytz.timezone(user_timezone)
                    current_time = datetime.now(user_tz).strftime("%H:%M:%S %Z")
                except:
                    current_time = datetime.now().strftime("%H:%M:%S UTC")

                sent_count = len(get_sent_messages_list())

                status_text = f"""
    📊 **Quick Status**
    🕒 Time: {current_time}
    📨 Messages: {sent_count} tracked
    💾 Database: ✅ Active
    🤖 Bot: ✅ Running
                """

                await query.edit_message_text(
                    status_text, parse_mode=ParseMode.MARKDOWN
                )

            except Exception as e:
                await query.edit_message_text("❌ Error getting status")

        elif callback_data == "sources":
            # Show sources summary
            sources_text = "📰 **News Sources:**\n\n"
            for category, config in self.news_categories_dict.items():
                emoji = NEWS_CATEGORIES[category]["emoji"]
                count = len(config["news_sources"])
                sources_text += f"{emoji} {category.title()}: {count} sources\n"

            await query.edit_message_text(sources_text, parse_mode=ParseMode.MARKDOWN)

        elif callback_data.startswith("dashboard_"):
            dashboard_action = callback_data.replace("dashboard_", "")

            if dashboard_action == "refresh":
                # Refresh dashboard data
                dashboard_text = await self.get_dashboard_data()

                # Add dashboard navigation buttons
                keyboard = [
                    [
                        InlineKeyboardButton(
                            "📊 Detailed Stats", callback_data="dashboard_detailed"
                        ),
                        InlineKeyboardButton(
                            "📈 Last 7 Days", callback_data="dashboard_week"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "👥 User Stats", callback_data="dashboard_users"
                        ),
                        InlineKeyboardButton(
                            "🔄 Refresh", callback_data="dashboard_refresh"
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 Back to Main", callback_data="main_menu"
                        )
                    ],
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    dashboard_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup,
                )

            elif dashboard_action == "detailed":
                # Show detailed analytics
                try:
                    with sqlite3.connect("news_bot.db") as conn:
                        cursor = conn.cursor()

                        # Get weekly stats
                        cursor.execute("""
                            SELECT DATE(sent_at) as date, COUNT(*) as count
                            FROM sent_messages
                            WHERE sent_at >= datetime('now', '-7 days')
                            GROUP BY DATE(sent_at)
                            ORDER BY date DESC
                        """)
                        weekly_stats = cursor.fetchall()

                        # Get source breakdown
                        cursor.execute("""
                            SELECT source, COUNT(*) as count
                            FROM sent_messages
                            WHERE sent_at >= datetime('now', '-7 days') AND source IS NOT NULL
                            GROUP BY source
                            ORDER BY count DESC
                            LIMIT 5
                        """)
                        source_stats = cursor.fetchall()

                    detailed_text = "📊 **Detailed Analytics (Last 7 Days)**\n\n"

                    detailed_text += "📈 **Daily Activity:**\n"
                    for date, count in weekly_stats:
                        detailed_text += f"• {date}: {count} articles\n"

                    detailed_text += "\n🌐 **Top Sources:**\n"
                    for source, count in source_stats:
                        detailed_text += f"• {source}: {count} articles\n"

                    await query.edit_message_text(
                        detailed_text, parse_mode=ParseMode.MARKDOWN
                    )

                except Exception as e:
                    await query.edit_message_text("❌ Error loading detailed stats")

            elif dashboard_action == "week":
                # Show last 7 days summary
                try:
                    with sqlite3.connect("news_bot.db") as conn:
                        cursor = conn.cursor()

                        cursor.execute("""
                            SELECT category, COUNT(*) as count
                            FROM sent_messages
                            WHERE sent_at >= datetime('now', '-7 days') AND category IS NOT NULL
                            GROUP BY category
                            ORDER BY count DESC
                        """)
                        week_stats = cursor.fetchall()

                    week_text = "📅 **Last 7 Days Summary**\n\n"
                    total_week = sum(count for _, count in week_stats)
                    week_text += f"📊 **Total Articles:** {total_week}\n\n"

                    week_text += "📂 **By Category:**\n"
                    for category, count in week_stats:
                        emoji = NEWS_CATEGORIES.get(category, {}).get("emoji", "📰")
                        percentage = (count / total_week * 100) if total_week > 0 else 0
                        week_text += (
                            f"{emoji} {category}: {count} ({percentage:.1f}%)\n"
                        )

                    await query.edit_message_text(
                        week_text, parse_mode=ParseMode.MARKDOWN
                    )

                except Exception as e:
                    await query.edit_message_text("❌ Error loading weekly stats")

            elif dashboard_action == "users":
                # Show user statistics
                try:
                    user_stats = get_user_stats()

                    users_text = f"""👥 **User Statistics**

    📊 **Total Users:** {user_stats["total_users"]}
    🆕 **New Today:** {user_stats["new_today"]}
    🔥 **Active (7 days):** {user_stats["active_users"]}

    📈 **Growth Rate:**
    {f"• {((user_stats['new_today'] / max(user_stats['total_users'], 1)) * 100):.1f}% daily growth" if user_stats["total_users"] > 0 else "• No data available"}

    💪 **Engagement:**
    {f"• {((user_stats['active_users'] / max(user_stats['total_users'], 1)) * 100):.1f}% active users" if user_stats["total_users"] > 0 else "• No data available"}

    *Statistics updated in real-time*
                    """

                    await query.edit_message_text(
                        users_text, parse_mode=ParseMode.MARKDOWN
                    )

                except Exception as e:
                    await query.edit_message_text("❌ Error loading user stats")

        elif callback_data == "settings":
            # Show main settings menu
            user_prefs = get_user_preferences(query.from_user.id)

            settings_text = f"""⚙️ **Your Settings**

    📂 **Subscribed Categories:**
    {", ".join([cat.title() for cat in user_prefs.get("subscribed_categories", [])]) or "None"}

    ⏰ **Preferred Time:**
    {user_prefs.get("preferred_time") or "Not set"}

    📊 **Daily Limit:**
    {user_prefs.get("daily_limit", 5)} articles per category

    🔔 **Notifications:**
    {"✅ Enabled" if user_prefs.get("notifications", True) else "❌ Disabled"}

    👆 **Choose what to configure:**
            """

            keyboard = [
                [
                    InlineKeyboardButton(
                        "📂 Manage Categories", callback_data="settings_categories"
                    )
                ],
                [InlineKeyboardButton("⏰ Set Time", callback_data="settings_time")],
                [
                    InlineKeyboardButton(
                        "📊 Daily Limit", callback_data="settings_limit"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔔 Notifications", callback_data="settings_notifications"
                    )
                ],
                [InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")],
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                settings_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )

        # Handle individual settings sub-menus
        elif callback_data == "settings_categories":
            await self.show_categories_menu(query)

        elif callback_data == "settings_time":
            await self.show_time_menu(query)

        elif callback_data == "settings_limit":
            await self.show_limit_menu(query)

        elif callback_data == "settings_notifications":
            await self.show_notifications_menu(query)

        # Handle category toggle actions
        elif callback_data.startswith("toggle_cat_"):
            category = callback_data.replace("toggle_cat_", "")
            user_id = query.from_user.id
            user_prefs = get_user_preferences(user_id)
            current_cats = user_prefs.get("subscribed_categories", [])

            if category in current_cats:
                current_cats.remove(category)
                action = "unsubscribed from"
            else:
                current_cats.append(category)
                action = "subscribed to"

            update_user_preferences(user_id, subscribed_categories=current_cats)

            # Update schedule
            if self.scheduler_manager:
                await self.scheduler_manager.update_user_schedule(user_id)

            await query.answer(f"✅ {action.title()} {category}!")

            # Refresh the categories menu
            await self.show_categories_menu(query)

        # Handle bulk category actions
        elif callback_data == "sub_all_cats":
            user_id = query.from_user.id
            all_categories = list(NEWS_CATEGORIES.keys())
            update_user_preferences(user_id, subscribed_categories=all_categories)

            # Update schedule
            if self.scheduler_manager:
                await self.scheduler_manager.update_user_schedule(user_id)

            await query.answer("✅ Subscribed to all categories!")
            await self.show_categories_menu(query)

        elif callback_data == "unsub_all_cats":
            user_id = query.from_user.id
            update_user_preferences(user_id, subscribed_categories=[])

            # Update schedule
            if self.scheduler_manager:
                await self.scheduler_manager.update_user_schedule(user_id)

            await query.answer("✅ Unsubscribed from all categories!")
            await self.show_categories_menu(query)

        # Handle time setting actions
        elif callback_data.startswith("set_time_"):
            time_str = callback_data.replace("set_time_", "")
            user_id = query.from_user.id
            update_user_preferences(user_id, preferred_time=time_str)

            # Update schedule
            if self.scheduler_manager:
                await self.scheduler_manager.update_user_schedule(user_id)

            await query.answer(f"✅ Time set to {time_str}!")
            await self.show_time_menu(query)

        elif callback_data == "clear_time":
            user_id = query.from_user.id
            update_user_preferences(user_id, preferred_time=None)

            # Update schedule (this will remove the schedule)
            if self.scheduler_manager:
                await self.scheduler_manager.update_user_schedule(user_id)

            await query.answer("✅ Time preference cleared!")
            await self.show_time_menu(query)

        # Handle limit setting actions
        elif callback_data.startswith("set_limit_"):
            limit = int(callback_data.replace("set_limit_", ""))
            user_id = query.from_user.id
            update_user_preferences(user_id, daily_limit=limit)

            # Note: Daily limit doesn't affect scheduling, just manual requests
            # But we can still update in case we want to use it for scheduled news later

            await query.answer(f"✅ Limit set to {limit} articles!")
            await self.show_limit_menu(query)

        # Handle notification actions
        elif callback_data == "enable_notifications":
            user_id = query.from_user.id
            update_user_preferences(user_id, notifications=True)

            # Update schedule (this will enable scheduled delivery)
            if self.scheduler_manager:
                await self.scheduler_manager.update_user_schedule(user_id)

            await query.answer("✅ Notifications enabled!")
            await self.show_notifications_menu(query)

        elif callback_data == "disable_notifications":
            user_id = query.from_user.id
            update_user_preferences(user_id, notifications=False)

            # Update schedule (this will disable scheduled delivery)
            if self.scheduler_manager:
                await self.scheduler_manager.update_user_schedule(user_id)

            await query.answer("✅ Notifications disabled!")
            await self.show_notifications_menu(query)

        # Handle timezone setting
        elif callback_data == "settings_timezone":
            await self.show_timezone_menu(query)

        # Handle timezone selection
        elif callback_data.startswith("set_tz_"):
            timezone = callback_data.replace("set_tz_", "")
            user_id = query.from_user.id

            try:
                # Validate timezone
                pytz.timezone(timezone)

                # Debug: Log before update
                old_prefs = get_user_preferences(user_id)
                logger.info(
                    f"Before timezone update - User {user_id} prefs: {old_prefs}"
                )

                # Update timezone
                update_user_preferences(user_id, timezone=timezone)

                # Update schedule
                if self.scheduler_manager:
                    await self.scheduler_manager.update_user_schedule(user_id)

                # Debug: Log after update
                new_prefs = get_user_preferences(user_id)
                logger.info(
                    f"After timezone update - User {user_id} prefs: {new_prefs}"
                )

                # Get current time in new timezone
                user_tz = pytz.timezone(timezone)
                local_time = datetime.now(user_tz).strftime("%H:%M")
                tz_name = datetime.now(user_tz).strftime("%Z")

                await query.answer(
                    f"✅ Timezone set to {timezone}! Currently {local_time} {tz_name}"
                )

                # Directly show the time menu instead of going back to timezone selection
                await self.show_time_menu(query)

            except Exception as e:
                logger.error(f"Timezone setting error: {e}")
                await query.answer("❌ Invalid timezone!")
                await self.show_timezone_menu(query)

        # Handle main menu button
        elif callback_data == "main_menu":
            await self.show_main_menu(query)

    async def show_categories_menu(self, query):
        """Show categories management sub-menu."""
        user_prefs = get_user_preferences(query.from_user.id)
        current_categories = user_prefs.get("subscribed_categories", [])

        categories_text = f"""📂 **Category Management**

🔘 **Currently Subscribed:**
{", ".join([cat.title() for cat in current_categories]) or "None"}

👆 **Choose an action:**
        """

        keyboard = []
        # Add individual category buttons
        for category, data in NEWS_CATEGORIES.items():
            status = "✅" if category in current_categories else "➕"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{status} {data['emoji']} {category.title()}",
                        callback_data=f"toggle_cat_{category}",
                    )
                ]
            )

        # Add bulk actions
        keyboard.append(
            [
                InlineKeyboardButton("✅ Subscribe All", callback_data="sub_all_cats"),
                InlineKeyboardButton(
                    "❌ Unsubscribe All", callback_data="unsub_all_cats"
                ),
            ]
        )
        keyboard.append(
            [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings")]
        )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            categories_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    async def show_time_menu(self, query):
        """Show time setting sub-menu."""
        user_prefs = get_user_preferences(query.from_user.id)
        current_time = user_prefs.get("preferred_time", "Not set")
        current_timezone = user_prefs.get("timezone", "UTC")

        # Get current time in user's timezone and debug info
        try:
            user_tz = pytz.timezone(current_timezone)
            local_time = datetime.now(user_tz).strftime("%H:%M")
            tz_name = datetime.now(user_tz).strftime("%Z")
            tz_display = f"{current_timezone} (currently {local_time} {tz_name})"
        except Exception as e:
            logger.error(f"Timezone error: {e}")
            tz_display = f"{current_timezone} (timezone error)"

        # Debug: log the user preferences
        logger.info(f"User {query.from_user.id} preferences: {user_prefs}")

        time_text = f"""⏰ **Time Preferences**

    🕐 **Current Schedule:** {current_time}
    🌍 **Your Timezone:** {tz_display}

    👆 **Choose a preset time:**
        """

        keyboard = [
            [
                InlineKeyboardButton(
                    "🌅 06:00 Morning", callback_data="set_time_06:00"
                ),
                InlineKeyboardButton(
                    "🌇 08:00 Breakfast", callback_data="set_time_08:00"
                ),
            ],
            [
                InlineKeyboardButton("☕ 12:00 Lunch", callback_data="set_time_12:00"),
                InlineKeyboardButton(
                    "🌆 18:00 Evening", callback_data="set_time_18:00"
                ),
            ],
            [
                InlineKeyboardButton("🌃 20:00 Night", callback_data="set_time_20:00"),
                InlineKeyboardButton("❌ Clear Time", callback_data="clear_time"),
            ],
            [
                InlineKeyboardButton(
                    "🌍 Change Timezone", callback_data="settings_timezone"
                )
            ],
            [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            time_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    async def show_limit_menu(self, query):
        """Show daily limit sub-menu."""
        user_prefs = get_user_preferences(query.from_user.id)
        current_limit = user_prefs.get("daily_limit", 5)

        limit_text = f"""📊 **Daily Article Limit**

📈 **Current Limit:** {current_limit} articles per category

👆 **Choose a new limit:**
        """

        keyboard = [
            [
                InlineKeyboardButton("1️⃣ 1 article", callback_data="set_limit_1"),
                InlineKeyboardButton("3️⃣ 3 articles", callback_data="set_limit_3"),
            ],
            [
                InlineKeyboardButton("5️⃣ 5 articles", callback_data="set_limit_5"),
                InlineKeyboardButton("🔟 10 articles", callback_data="set_limit_10"),
            ],
            [
                InlineKeyboardButton("1️⃣5️⃣ 15 articles", callback_data="set_limit_15"),
                InlineKeyboardButton("2️⃣0️⃣ 20 articles", callback_data="set_limit_20"),
            ],
            [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            limit_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    async def show_notifications_menu(self, query):
        """Show notifications toggle."""
        user_prefs = get_user_preferences(query.from_user.id)
        current_notifications = user_prefs.get("notifications", True)

        notifications_text = f"""🔔 **Notification Settings**

🔊 **Current Status:** {"✅ Enabled" if current_notifications else "❌ Disabled"}

👆 **Choose action:**
        """

        keyboard = [
            [
                InlineKeyboardButton(
                    "🔔 Enable Notifications", callback_data="enable_notifications"
                ),
                InlineKeyboardButton(
                    "🔕 Disable Notifications", callback_data="disable_notifications"
                ),
            ],
            [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings")],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            notifications_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    async def show_timezone_menu(self, query):
        """Show timezone selection menu."""
        user_prefs = get_user_preferences(query.from_user.id)
        current_timezone = user_prefs.get("timezone", "UTC")

        # Get current time in user's current timezone
        try:
            current_tz = pytz.timezone(current_timezone)
            current_time = datetime.now(current_tz).strftime("%H:%M")
            current_tz_name = datetime.now(current_tz).strftime("%Z")
            tz_display = f"{current_timezone} ({current_time} {current_tz_name})"
        except:
            tz_display = current_timezone

        # Add a timestamp to ensure message content changes
        update_time = datetime.now().strftime("%H:%M:%S")

        timezone_text = f"""🌍 **Timezone Settings** ⏰ {update_time}

🗺️ **Current Timezone:** {tz_display}

👆 **Select your timezone:**
        """

        # Get current time for each timezone to display
        now_utc = datetime.now(pytz.UTC)

        def get_tz_display(tz_name, flag, description):
            try:
                tz = pytz.timezone(tz_name)
                local_time = now_utc.astimezone(tz)
                time_str = local_time.strftime("%H:%M")
                tz_abbrev = local_time.strftime("%Z")
                return f"{flag} {description} ({time_str} {tz_abbrev})"
            except:
                return f"{flag} {description}"

        # Common timezones with current times
        keyboard = [
            [
                InlineKeyboardButton(
                    get_tz_display("US/Eastern", "🇺🇸", "EST"),
                    callback_data="set_tz_US/Eastern",
                ),
                InlineKeyboardButton(
                    get_tz_display("US/Pacific", "🇺🇸", "PST"),
                    callback_data="set_tz_US/Pacific",
                ),
            ],
            [
                InlineKeyboardButton(
                    get_tz_display("Europe/London", "🇬🇧", "GMT"),
                    callback_data="set_tz_Europe/London",
                ),
                InlineKeyboardButton(
                    get_tz_display("Europe/Berlin", "🇩🇪", "CET"),
                    callback_data="set_tz_Europe/Berlin",
                ),
            ],
            [
                InlineKeyboardButton(
                    get_tz_display("Asia/Tokyo", "🇯🇵", "JST"),
                    callback_data="set_tz_Asia/Tokyo",
                ),
                InlineKeyboardButton(
                    get_tz_display("Australia/Sydney", "🇦🇺", "AEST"),
                    callback_data="set_tz_Australia/Sydney",
                ),
            ],
            [
                InlineKeyboardButton(
                    get_tz_display("Asia/Kolkata", "🇮🇳", "IST"),
                    callback_data="set_tz_Asia/Kolkata",
                ),
                InlineKeyboardButton(
                    get_tz_display("Asia/Shanghai", "🇨🇳", "CST"),
                    callback_data="set_tz_Asia/Shanghai",
                ),
            ],
            [
                InlineKeyboardButton(
                    get_tz_display("America/Sao_Paulo", "🇧🇷", "BRT"),
                    callback_data="set_tz_America/Sao_Paulo",
                ),
                InlineKeyboardButton(
                    get_tz_display("Europe/Moscow", "🇷🇺", "MSK"),
                    callback_data="set_tz_Europe/Moscow",
                ),
            ],
            [
                InlineKeyboardButton(
                    get_tz_display("UTC", "🌐", "UTC"), callback_data="set_tz_UTC"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔙 Back to Time Settings", callback_data="settings_time"
                )
            ],
        ]

        try:
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                timezone_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )
        except Exception as e:
            # If message edit fails, try to send a new message
            logger.warning(f"Could not edit message, trying to send new one: {e}")
            await query.message.reply_text(
                timezone_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
            )

    async def show_main_menu(self, query):
        """Show main welcome menu."""
        user = query.from_user
        user_prefs = get_user_preferences(user.id)

        welcome_text = f"""
    👋 **Hi {user.first_name}!**

    Ready for some news? Just pick what you're interested in:
        """

        # Create simple action-focused keyboard (same as /start)
        keyboard = [
            [InlineKeyboardButton("📰 Get News", callback_data="show_news_menu")],
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                InlineKeyboardButton("📊 Dashboard", callback_data="dashboard_refresh"),
            ],
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )

    async def error_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle errors."""
        logger.error(f"Update {update} caused error {context.error}")

        if update and update.message:
            await update.message.reply_text(
                "❌ An error occurred. Please try again later."
            )

    def run(self):
        """Run the Telegram bot using the Application run_polling method."""
        try:
            # Just use the synchronous approach
            logger.info("Starting Telegram News Bot")

            # Setup configuration
            self.setup_config()

            # Initialize database
            init_database()
            cleanup_old_messages(30)

            # Create application
            application = Application.builder().token(self.bot_token).build()
            self.application = application

            # Add handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("help", self.help_command))
            application.add_handler(CommandHandler("news", self.news_command))
            application.add_handler(CommandHandler("status", self.status_command))
            application.add_handler(CommandHandler("sources", self.sources_command))
            application.add_handler(CommandHandler("dashboard", self.dashboard_command))
            application.add_handler(CommandHandler("schedule", self.schedule_command))
            application.add_handler(CommandHandler("settings", self.settings_command))
            application.add_handler(
                CommandHandler("scheduled", self.scheduled_users_command)
            )  # Add this
            application.add_handler(CallbackQueryHandler(self.button_callback))
            application.add_error_handler(self.error_handler)

            # Initialize scheduler AFTER application is set up
            async def post_init(application):  # Fixed: Added application parameter
                await self.setup_scheduler()

            # Set up post-init task
            application.post_init = post_init

            # Run the bot
            logger.info("Bot is running...")
            application.run_polling(allowed_updates=Update.ALL_TYPES)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            if self.scheduler_manager:
                self.scheduler_manager.shutdown()
        except Exception as e:
            logger.error(f"Critical error in Telegram bot: {e}")
            if self.scheduler_manager:
                self.scheduler_manager.shutdown()
            print(f"❌ Critical error: {e}")
            print("💡 Check your .env file and ensure all API keys are set correctly")
            raise


def check_python_version():
    """Check if Python version is compatible."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print(f"❌ Python {version.major}.{version.minor} is not supported.")
        print("✅ Please use Python 3.9 or higher (3.12 recommended)")
        print("🔗 Download Python 3.12: https://www.python.org/downloads/")
        sys.exit(1)

    if version.minor >= 12:
        print(
            f"✅ Python {version.major}.{version.minor}.{version.micro} - Excellent choice!"
        )
    else:
        print(
            f"⚠️  Python {version.major}.{version.minor}.{version.micro} - Compatible but consider upgrading to 3.12"
        )


def main():
    """Main function to run the Telegram bot."""
    print("🤖 Starting Telegram News Bot...")

    # Check Python version compatibility
    check_python_version()

    try:
        bot = NewsTelegramBot()
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user. Goodbye!")
    except Exception as e:
        print(f"❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
