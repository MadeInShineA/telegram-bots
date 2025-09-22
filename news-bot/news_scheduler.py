#!/usr/bin/env python3
"""
News Scheduler Module
Handles automatic news delivery at user-specified times.
"""

import asyncio
import logging
import sqlite3
import json
from datetime import datetime
from typing import Dict, List
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit

# Import database functions
from news_processor import get_user_preferences

logger = logging.getLogger(__name__)


class NewsScheduler:
    def __init__(self, bot_instance):
        self.bot = bot_instance
        self.scheduler = None

    async def start(self):
        """Initialize and start the scheduler."""
        try:
            self.scheduler = AsyncIOScheduler()
            self.scheduler.start()
            logger.info("News scheduler started successfully")

            # Load existing user schedules from database
            await self.load_user_schedules()

            # Register cleanup on exit
            atexit.register(self.shutdown)

            return True

        except Exception as e:
            logger.error(f"Error starting news scheduler: {e}")
            return False

    def shutdown(self):
        """Clean shutdown of scheduler."""
        if self.scheduler:
            try:
                self.scheduler.shutdown()
                logger.info("News scheduler shut down successfully")
            except Exception as e:
                logger.error(f"Error shutting down scheduler: {e}")

    async def load_user_schedules(self):
        """Load all user preferred times and schedule them."""
        try:
            with sqlite3.connect("db.sql") as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT user_id, preferred_time, timezone, subscribed_categories
                    FROM user_preferences 
                    WHERE preferred_time IS NOT NULL 
                    AND notifications = 1
                """)

                users = cursor.fetchall()

            scheduled_count = 0
            for user_id, preferred_time, timezone, subscribed_categories_str in users:
                if preferred_time and timezone:
                    try:
                        # Parse subscribed categories
                        subscribed_categories = self._parse_categories(
                            subscribed_categories_str
                        )

                        # Schedule for this user
                        await self.schedule_user_news(
                            user_id, preferred_time, timezone, subscribed_categories
                        )
                        scheduled_count += 1

                    except Exception as e:
                        logger.error(f"Error scheduling for user {user_id}: {e}")

            logger.info(f"Loaded {scheduled_count} user schedules")

        except Exception as e:
            logger.error(f"Error loading user schedules: {e}")

    def _parse_categories(self, categories_str):
        """Parse categories from database format."""
        try:
            if isinstance(categories_str, str):
                # Handle JSON string format
                if categories_str.startswith("["):
                    return json.loads(categories_str)
                # Handle comma-separated format
                elif "," in categories_str:
                    return [cat.strip() for cat in categories_str.split(",")]
                else:
                    return [categories_str]
            elif isinstance(categories_str, list):
                return categories_str
            else:
                # Default to all categories if parsing fails
                from telegram_bot import NEWS_CATEGORIES

                return list(NEWS_CATEGORIES.keys())
        except Exception as e:
            logger.error(f"Error parsing categories: {e}")
            from telegram_bot import NEWS_CATEGORIES

            return list(NEWS_CATEGORIES.keys())

    async def schedule_user_news(
        self, user_id: int, preferred_time: str, timezone: str, categories: list
    ):
        """Schedule daily news for a specific user."""
        try:
            hour, minute = map(int, preferred_time.split(":"))

            # Create unique job ID for this user
            job_id = f"daily_news_{user_id}"

            # Remove existing job if it exists
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            # Validate timezone
            try:
                pytz.timezone(timezone)
            except Exception:
                timezone = "UTC"
                logger.warning(f"Invalid timezone for user {user_id}, using UTC")

            # Add new job
            self.scheduler.add_job(
                func=self._send_scheduled_news_to_user,
                trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
                args=[user_id, categories],
                id=job_id,
                name=f"Daily news for user {user_id}",
                misfire_grace_time=3600,  # Allow 1 hour grace period if bot was down
            )

            logger.info(
                f"Scheduled daily news for user {user_id} at {preferred_time} ({timezone})"
            )

        except Exception as e:
            logger.error(f"Error scheduling news for user {user_id}: {e}")

    async def _send_scheduled_news_to_user(self, user_id: int, categories: list):
        """Send scheduled news to a specific user."""
        try:
            logger.info(f"Sending scheduled news to user {user_id}")

            # Check if user still has notifications enabled
            user_prefs = get_user_preferences(user_id)
            if not user_prefs.get("notifications", False):
                logger.info(f"User {user_id} has notifications disabled, skipping")
                return

            # Send news for each subscribed category
            total_articles = 0
            sent_categories = []

            for category in categories:
                if category in self.bot.news_categories_dict:
                    try:
                        config = self.bot.news_categories_dict[category]
                        news_sources = config["news_sources"]

                        articles_sent = await self.bot.send_news_to_dm(
                            user_id, category, news_sources
                        )
                        if articles_sent > 0:
                            total_articles += articles_sent
                            sent_categories.append(category)

                        # Small delay between categories
                        await asyncio.sleep(2)

                    except Exception as e:
                        logger.error(
                            f"Error sending {category} news to user {user_id}: {e}"
                        )

            # Send summary message if any articles were sent
            if total_articles > 0:
                await self._send_summary_message(
                    user_id, total_articles, sent_categories
                )
            else:
                logger.info(f"No new articles to send to user {user_id}")

            logger.info(
                f"Completed scheduled news for user {user_id}: {total_articles} articles"
            )

        except Exception as e:
            logger.error(f"Error in scheduled news delivery for user {user_id}: {e}")

    async def _send_summary_message(
        self, user_id: int, total_articles: int, categories: list
    ):
        """Send a summary message after scheduled delivery."""
        try:
            from telegram.constants import ParseMode

            # Get user's timezone for the summary
            user_prefs = get_user_preferences(user_id)
            user_timezone = user_prefs.get("timezone", "UTC")

            try:
                user_tz = pytz.timezone(user_timezone)
                current_time = datetime.now(user_tz).strftime("%H:%M")
            except:
                current_time = datetime.now().strftime("%H:%M")

            # Create category list with emojis
            from telegram_bot import NEWS_CATEGORIES

            category_list = []
            for cat in categories:
                emoji = NEWS_CATEGORIES.get(cat, {}).get("emoji", "📰")
                category_list.append(f"{emoji} {cat.title()}")

            summary_msg = f"""📅 **Daily News Delivered** ({current_time})

📊 **Summary:**
• {total_articles} article{"s" if total_articles != 1 else ""} sent
• Categories: {", ".join(category_list)}

_Use /settings to modify your preferences or /news to get more articles._"""

            await self.bot.application.bot.send_message(
                chat_id=user_id, text=summary_msg, parse_mode=ParseMode.MARKDOWN
            )

        except Exception as e:
            logger.error(f"Error sending summary to user {user_id}: {e}")

    async def update_user_schedule(self, user_id: int):
        """Update user's schedule when preferences change."""
        try:
            user_prefs = get_user_preferences(user_id)
            preferred_time = user_prefs.get("preferred_time")
            timezone = user_prefs.get("timezone", "UTC")
            subscribed_categories = user_prefs.get("subscribed_categories", [])
            notifications = user_prefs.get("notifications", False)

            job_id = f"daily_news_{user_id}"

            # Remove existing job
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"Removed old schedule for user {user_id}")

            # Add new job if user has notifications enabled and preferred time set
            if notifications and preferred_time:
                if not subscribed_categories:
                    # Default to all categories if none selected
                    from telegram_bot import NEWS_CATEGORIES

                    subscribed_categories = list(NEWS_CATEGORIES.keys())

                await self.schedule_user_news(
                    user_id, preferred_time, timezone, subscribed_categories
                )
                logger.info(f"Updated schedule for user {user_id}")
            else:
                logger.info(
                    f"Schedule disabled for user {user_id} (notifications: {notifications}, time: {preferred_time})"
                )

        except Exception as e:
            logger.error(f"Error updating schedule for user {user_id}: {e}")

    def remove_user_schedule(self, user_id: int):
        """Remove user's scheduled news delivery."""
        try:
            job_id = f"daily_news_{user_id}"
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info(f"Removed schedule for user {user_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error removing schedule for user {user_id}: {e}")
            return False

    def get_scheduled_users(self) -> List[Dict]:
        """Get list of all scheduled users."""
        try:
            jobs = self.scheduler.get_jobs()
            scheduled_users = []

            for job in jobs:
                if job.id.startswith("daily_news_"):
                    user_id = int(job.id.replace("daily_news_", ""))
                    next_run = job.next_run_time

                    scheduled_users.append(
                        {
                            "user_id": user_id,
                            "job_name": job.name,
                            "next_run": next_run.strftime("%Y-%m-%d %H:%M %Z")
                            if next_run
                            else "Not scheduled",
                            "timezone": str(job.trigger.timezone)
                            if hasattr(job.trigger, "timezone")
                            else "Unknown",
                        }
                    )

            return scheduled_users

        except Exception as e:
            logger.error(f"Error getting scheduled users: {e}")
            return []
