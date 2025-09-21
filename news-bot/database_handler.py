#!/usr/bin/env python3
"""
Database Handler - News Bot Database Operations
Handles all SQLite database operations for the news bot with user-based tracking.
"""

import sqlite3
import logging
import json
import os
import time
from typing import Optional, Dict, List, Any
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)


class NewsDatabase:
    def __init__(self, db_path: str = "db.sql"):
        self.db_path = db_path
        self.init_database()

    def init_database(self) -> None:
        """Initialize SQLite database with required tables."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Create sent_messages table with user_id (no UNIQUE constraint on title)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS sent_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        url TEXT,
                        category TEXT,
                        source TEXT,
                        user_id INTEGER,
                        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Check if user_id column exists in sent_messages, if not add it
                cursor.execute("PRAGMA table_info(sent_messages)")
                columns = [column[1] for column in cursor.fetchall()]

                if "user_id" not in columns:
                    cursor.execute(
                        "ALTER TABLE sent_messages ADD COLUMN user_id INTEGER"
                    )
                    logger.info("Added user_id column to sent_messages table")

                # Check if there's a UNIQUE constraint on title and remove it if exists
                cursor.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='sent_messages'"
                )
                table_sql = cursor.fetchone()
                if table_sql and "UNIQUE" in table_sql[0] and "title" in table_sql[0]:
                    # Recreate table without UNIQUE constraint
                    cursor.execute("""
                        CREATE TABLE sent_messages_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title TEXT NOT NULL,
                            url TEXT,
                            category TEXT,
                            source TEXT,
                            user_id INTEGER,
                            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)

                    cursor.execute("""
                        INSERT INTO sent_messages_new (title, url, category, source, user_id, sent_at)
                        SELECT title, url, category, source, user_id, sent_at FROM sent_messages
                    """)

                    cursor.execute("DROP TABLE sent_messages")
                    cursor.execute(
                        "ALTER TABLE sent_messages_new RENAME TO sent_messages"
                    )
                    logger.info("Removed UNIQUE constraint from title column")

                # Create index for better performance on user-specific queries
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sent_messages_user_title 
                    ON sent_messages(user_id, title)
                """)

                # Create bot_statistics table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS bot_statistics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        source TEXT NOT NULL,
                        articles_processed INTEGER DEFAULT 0,
                        articles_sent INTEGER DEFAULT 0,
                        run_date DATE DEFAULT CURRENT_DATE,
                        run_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create users table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        is_active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Create user_preferences table with timezone field
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_preferences (
                        user_id INTEGER PRIMARY KEY,
                        subscribed_categories TEXT DEFAULT 'technology,science,sports,business',
                        preferred_time TEXT,
                        language TEXT DEFAULT 'en',
                        daily_limit INTEGER DEFAULT 5,
                        notifications BOOLEAN DEFAULT 1,
                        timezone TEXT DEFAULT 'UTC',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users (user_id)
                    )
                """)

                # Add timezone column if it doesn't exist (for existing databases)
                try:
                    cursor.execute("SELECT timezone FROM user_preferences LIMIT 1")
                except sqlite3.OperationalError:
                    # Column doesn't exist, add it
                    cursor.execute(
                        "ALTER TABLE user_preferences ADD COLUMN timezone TEXT DEFAULT 'UTC'"
                    )
                    logger.info("Added timezone column to user_preferences table")

                # Create scheduled_jobs table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS scheduled_jobs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        job_name TEXT NOT NULL UNIQUE,
                        category TEXT,
                        schedule_time TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_run TIMESTAMP,
                        next_run TIMESTAMP
                    )
                """)

                # Create dashboard_metrics table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dashboard_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        metric_date DATE DEFAULT CURRENT_DATE,
                        total_articles_processed INTEGER DEFAULT 0,
                        total_articles_sent INTEGER DEFAULT 0,
                        total_api_calls INTEGER DEFAULT 0,
                        total_errors INTEGER DEFAULT 0,
                        avg_processing_time REAL DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                conn.commit()
                logger.info("Database initialized successfully")

        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise

    def is_message_sent(self, title: str, user_id: int = None) -> bool:
        """Check if a message with this title has already been sent to a specific user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                if user_id is not None:
                    # Check for specific user
                    cursor.execute(
                        "SELECT 1 FROM sent_messages WHERE title = ? AND user_id = ? LIMIT 1",
                        (title, user_id),
                    )
                else:
                    # Global check for backward compatibility
                    cursor.execute(
                        "SELECT 1 FROM sent_messages WHERE title = ? LIMIT 1", (title,)
                    )

                return cursor.fetchone() is not None

        except sqlite3.Error as e:
            logger.error(f"Error checking sent message: {e}")
            return False

    def record_sent_message(
        self,
        title: str,
        url: str = None,
        category: str = None,
        source: str = None,
        user_id: int = None,
    ) -> bool:
        """Record a sent message in the database for a specific user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                if user_id is not None:
                    # Check if already sent to this user
                    cursor.execute(
                        "SELECT 1 FROM sent_messages WHERE title = ? AND user_id = ?",
                        (title, user_id),
                    )
                    if cursor.fetchone():
                        logger.debug(f"Message already sent to user {user_id}: {title}")
                        return False

                    # Insert for specific user
                    cursor.execute(
                        """
                        INSERT INTO sent_messages (title, url, category, source, user_id)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (title, url, category, source, user_id),
                    )
                else:
                    # Backward compatibility - global record
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO sent_messages (title, url, category, source)
                        VALUES (?, ?, ?, ?)
                    """,
                        (title, url, category, source),
                    )

                conn.commit()

                if cursor.rowcount > 0:
                    logger.debug(f"Recorded sent message for user {user_id}: {title}")
                    return True
                else:
                    return False

        except sqlite3.Error as e:
            logger.error(f"Error recording sent message: {e}")
            return False

    def get_user_sent_messages(self, user_id: int, limit: int = 100) -> List[str]:
        """Get list of sent message titles for a specific user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """SELECT title FROM sent_messages 
                       WHERE user_id = ? 
                       ORDER BY sent_at DESC 
                       LIMIT ?""",
                    (user_id, limit),
                )
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error getting user sent messages: {e}")
            return []

    def cleanup_old_messages(self, days: int = 30) -> None:
        """Remove old sent messages to keep database size manageable."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM sent_messages
                    WHERE sent_at < datetime('now', '-{} days')
                """.format(days)
                )

                deleted_count = cursor.rowcount
                conn.commit()

                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old messages")

        except sqlite3.Error as e:
            logger.error(f"Error cleaning up old messages: {e}")

    def cleanup_old_user_messages(self, user_id: int, days: int = 30) -> None:
        """Remove old sent messages for a specific user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM sent_messages
                    WHERE user_id = ? AND sent_at < datetime('now', '-{} days')
                """.format(days),
                    (user_id,),
                )

                deleted_count = cursor.rowcount
                conn.commit()

                if deleted_count > 0:
                    logger.info(
                        f"Cleaned up {deleted_count} old messages for user {user_id}"
                    )

        except sqlite3.Error as e:
            logger.error(f"Error cleaning up old messages for user {user_id}: {e}")

    def record_statistics(
        self, category: str, source: str, processed: int, sent: int
    ) -> None:
        """Record processing statistics for monitoring."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO bot_statistics (category, source, articles_processed, articles_sent)
                    VALUES (?, ?, ?, ?)
                """,
                    (category, source, processed, sent),
                )
                conn.commit()

        except sqlite3.Error as e:
            logger.error(f"Error recording statistics: {e}")

    def get_sent_messages_list(self) -> List[str]:
        """Get list of sent message titles for backwards compatibility."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT title FROM sent_messages ORDER BY sent_at DESC LIMIT 1000"
                )
                return [row[0] for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error getting sent messages: {e}")
            return []

    def register_user(
        self,
        user_id: int,
        username: str = None,
        first_name: str = None,
        last_name: str = None,
    ) -> None:
        """Register a new user or update existing user info."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Insert or update user
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, last_seen)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                    (user_id, username, first_name, last_name),
                )

                # Create default preferences if new user
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO user_preferences (user_id)
                    VALUES (?)
                """,
                    (user_id,),
                )

                conn.commit()
                logger.info(f"Registered/updated user: {user_id}")

        except sqlite3.Error as e:
            logger.error(f"Error registering user {user_id}: {e}")

    def get_user_preferences(self, user_id: int) -> Dict:
        """Get user preferences with timezone support."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT subscribed_categories, preferred_time, language, daily_limit, 
                           notifications, timezone
                    FROM user_preferences
                    WHERE user_id = ?
                """,
                    (user_id,),
                )

                result = cursor.fetchone()
                if result:
                    return {
                        "subscribed_categories": result[0].split(",")
                        if result[0]
                        else [],
                        "preferred_time": result[1],
                        "language": result[2],
                        "daily_limit": result[3],
                        "notifications": bool(result[4])
                        if result[4] is not None
                        else True,
                        "timezone": result[5] or "UTC",
                    }
                else:
                    # Return defaults for new user
                    return {
                        "subscribed_categories": [
                            "technology",
                            "science",
                            "sports",
                            "business",
                        ],
                        "preferred_time": None,
                        "language": "en",
                        "daily_limit": 5,
                        "notifications": True,
                        "timezone": "UTC",
                    }

        except sqlite3.Error as e:
            logger.error(f"Error getting user preferences for {user_id}: {e}")
            return {
                "subscribed_categories": [
                    "technology",
                    "science",
                    "sports",
                    "business",
                ],
                "preferred_time": None,
                "language": "en",
                "daily_limit": 5,
                "notifications": True,
                "timezone": "UTC",
            }

    def update_user_preferences(self, user_id: int, **kwargs) -> bool:
        """Update user preferences with timezone support."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Build dynamic update query
                update_fields = []
                values = []

                if "subscribed_categories" in kwargs:
                    update_fields.append("subscribed_categories = ?")
                    values.append(",".join(kwargs["subscribed_categories"]))

                if "preferred_time" in kwargs:
                    update_fields.append("preferred_time = ?")
                    values.append(kwargs["preferred_time"])

                if "language" in kwargs:
                    update_fields.append("language = ?")
                    values.append(kwargs["language"])

                if "daily_limit" in kwargs:
                    update_fields.append("daily_limit = ?")
                    values.append(kwargs["daily_limit"])

                if "notifications" in kwargs:
                    update_fields.append("notifications = ?")
                    values.append(kwargs["notifications"])

                if "timezone" in kwargs:
                    update_fields.append("timezone = ?")
                    values.append(kwargs["timezone"])

                if update_fields:
                    update_fields.append("updated_at = CURRENT_TIMESTAMP")
                    values.append(user_id)

                    query = f"""
                        UPDATE user_preferences
                        SET {", ".join(update_fields)}
                        WHERE user_id = ?
                    """

                    cursor.execute(query, values)

                    # If no rows were updated, insert new record
                    if cursor.rowcount == 0:
                        cursor.execute(
                            "INSERT INTO user_preferences (user_id) VALUES (?)",
                            (user_id,),
                        )
                        # Re-run the update
                        cursor.execute(query, values)

                    conn.commit()
                    logger.info(f"Updated preferences for user {user_id}: {kwargs}")
                    return True

            return False

        except sqlite3.Error as e:
            logger.error(f"Error updating preferences for user {user_id}: {e}")
            return False

    def get_user_stats(self) -> Dict:
        """Get user statistics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Total users
                cursor.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
                total_users = cursor.fetchone()[0]

                # New users today
                cursor.execute("""
                    SELECT COUNT(*) FROM users
                    WHERE DATE(created_at) = DATE('now') AND is_active = 1
                """)
                new_today = cursor.fetchone()[0]

                # Active users (used bot in last 7 days)
                cursor.execute("""
                    SELECT COUNT(*) FROM users
                    WHERE last_seen >= datetime('now', '-7 days') AND is_active = 1
                """)
                active_users = cursor.fetchone()[0]

                return {
                    "total_users": total_users,
                    "new_today": new_today,
                    "active_users": active_users,
                }

        except sqlite3.Error as e:
            logger.error(f"Error getting user stats: {e}")
            return {"total_users": 0, "new_today": 0, "active_users": 0}

    def get_scheduled_jobs(self) -> List[Dict]:
        """Get all scheduled jobs from database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
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

        except sqlite3.Error as e:
            logger.error(f"Error getting scheduled jobs: {e}")
            return []

    def add_scheduled_job(
        self, job_name: str, category: str, schedule_time: str
    ) -> bool:
        """Add a new scheduled job."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO scheduled_jobs
                    (job_name, category, schedule_time, is_active)
                    VALUES (?, ?, ?, 1)
                """,
                    (job_name, category, schedule_time),
                )
                conn.commit()
                return True

        except sqlite3.Error as e:
            logger.error(f"Error adding scheduled job: {e}")
            return False

    def remove_scheduled_job(self, job_name: str) -> bool:
        """Remove a scheduled job."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM scheduled_jobs WHERE job_name = ?", (job_name,)
                )
                conn.commit()
                return cursor.rowcount > 0

        except sqlite3.Error as e:
            logger.error(f"Error removing scheduled job: {e}")
            return False

    def toggle_scheduled_job(self, job_name: str) -> bool:
        """Toggle a scheduled job active/inactive."""
        try:
            with sqlite3.connect(self.db_path) as conn:
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
                conn.commit()
                return True

        except sqlite3.Error as e:
            logger.error(f"Error toggling scheduled job: {e}")
            return False

    def get_dashboard_data(self) -> Dict:
        """Get comprehensive dashboard data."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # Today's stats
                cursor.execute("""
                    SELECT COUNT(*) as total_sent,
                           COUNT(DISTINCT category) as categories_used,
                           COUNT(DISTINCT source) as sources_used
                    FROM sent_messages
                    WHERE DATE(sent_at) = DATE('now')
                """)
                today_stats = cursor.fetchone()

                # Total stats
                cursor.execute("""
                    SELECT COUNT(*) as total_messages,
                           COUNT(DISTINCT category) as total_categories,
                           MIN(sent_at) as first_message
                    FROM sent_messages
                """)
                total_stats = cursor.fetchone()

                # Category breakdown for today
                cursor.execute("""
                    SELECT category, COUNT(*) as count
                    FROM sent_messages
                    WHERE DATE(sent_at) = DATE('now') AND category IS NOT NULL
                    GROUP BY category
                    ORDER BY count DESC
                """)
                category_stats = cursor.fetchall()

                # Scheduled jobs count
                cursor.execute(
                    "SELECT COUNT(*) FROM scheduled_jobs WHERE is_active = 1"
                )
                active_jobs = cursor.fetchone()[0]

                return {
                    "today": {
                        "total_sent": today_stats[0],
                        "categories_used": today_stats[1],
                        "sources_used": today_stats[2],
                    },
                    "total": {
                        "messages": total_stats[0],
                        "categories": total_stats[1],
                        "first_message": total_stats[2],
                    },
                    "category_breakdown": dict(category_stats),
                    "active_jobs": active_jobs,
                }

        except sqlite3.Error as e:
            logger.error(f"Error getting dashboard data: {e}")
            return {}

    def migrate_json_to_db(self, json_file: str = "sent_messages.json") -> None:
        """Migrate existing JSON data to SQLite database."""
        if os.path.exists(json_file):
            try:
                with open(json_file, "r") as f:
                    sent_messages = json.load(f)

                logger.info(
                    f"Migrating {len(sent_messages)} messages from JSON to database"
                )

                for title in sent_messages:
                    self.record_sent_message(title)

                # Backup and remove JSON file
                backup_name = f"sent_messages_backup_{int(time.time())}.json"
                os.rename(json_file, backup_name)
                logger.info(
                    f"JSON file backed up to {backup_name} and migration completed"
                )

            except Exception as e:
                logger.error(f"Error migrating JSON data: {e}")
        else:
            logger.info("No JSON file found, starting with clean database")

    def execute_query(self, query: str, params: tuple = None) -> List[Dict]:
        """Execute a custom query and return results as dict list."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row  # This allows column access by name
                cursor = conn.cursor()

                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                return [dict(row) for row in cursor.fetchall()]

        except sqlite3.Error as e:
            logger.error(f"Error executing query: {e}")
            return []

    def close(self):
        """Close database connection (if needed for cleanup)."""
        # Since we use context managers, this is mainly for interface completeness
        pass


# Create a global instance for backward compatibility
_db_instance = None


def get_database() -> NewsDatabase:
    """Get the global database instance."""
    global _db_instance
    if _db_instance is None:
        _db_instance = NewsDatabase()
    return _db_instance


# Backward compatibility functions with user support
def init_database() -> None:
    """Initialize database (backward compatibility)."""
    get_database()


def is_message_sent(title: str, user_id: int = None) -> bool:
    """Check if message was sent (with user support)."""
    return get_database().is_message_sent(title, user_id)


def record_sent_message(
    title: str,
    url: str = None,
    category: str = None,
    source: str = None,
    user_id: int = None,
) -> bool:
    """Record sent message (with user support)."""
    return get_database().record_sent_message(title, url, category, source, user_id)


def cleanup_old_messages(days: int = 30) -> None:
    """Cleanup old messages (backward compatibility)."""
    get_database().cleanup_old_messages(days)


def record_statistics(category: str, source: str, processed: int, sent: int) -> None:
    """Record statistics (backward compatibility)."""
    get_database().record_statistics(category, source, processed, sent)


def get_sent_messages_list() -> List[str]:
    """Get sent messages list (backward compatibility)."""
    return get_database().get_sent_messages_list()


def register_user(
    user_id: int, username: str = None, first_name: str = None, last_name: str = None
) -> None:
    """Register user (backward compatibility)."""
    get_database().register_user(user_id, username, first_name, last_name)


def get_user_preferences(user_id: int) -> Dict:
    """Get user preferences (backward compatibility)."""
    return get_database().get_user_preferences(user_id)


def update_user_preferences(user_id: int, **kwargs) -> bool:
    """Update user preferences (backward compatibility)."""
    return get_database().update_user_preferences(user_id, **kwargs)


def get_user_stats() -> Dict:
    """Get user stats (backward compatibility)."""
    return get_database().get_user_stats()


def get_user_sent_messages(user_id: int, limit: int = 100) -> List[str]:
    """Get user sent messages (new function)."""
    return get_database().get_user_sent_messages(user_id, limit)


def cleanup_old_user_messages(user_id: int, days: int = 30) -> None:
    """Cleanup old user messages (new function)."""
    return get_database().cleanup_old_user_messages(user_id, days)
