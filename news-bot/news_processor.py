#!/usr/bin/env python3
"""
News Bot Core Functions - Python 3.12 Compatible
News processing, content extraction and API functions.
Database operations moved to database_handler.py
"""

import requests
import json
import logging
import time
import sys
from bs4 import BeautifulSoup
from bs4.element import Comment
from dotenv import load_dotenv
import datetime
import os
from typing import Optional, Dict, List, Any

# Import database functions
from database_handler import (
    init_database,
    is_message_sent,
    record_sent_message,
    cleanup_old_messages,
    record_statistics,
    get_sent_messages_list,
    register_user,
    get_user_preferences,
    update_user_preferences,
    get_user_stats,
    get_database,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("telegram_bot.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


def send_news_category(
    bot_token: str,
    bot_chatID: str,
    thread_id: str,
    news_data_key: str,
    textgear_api_key: str,
    news_category: str,
    news_sources: Dict,
    tags_to_avoid: List[str],
) -> None:
    """Send news for a specific category to Telegram thread."""
    try:
        logger.info(f"Starting news fetch for category: {news_category}")
        today = datetime.date.today().strftime("%B %d, %Y")
        starting_message = f"📰 *{today}'s {news_category.capitalize()} News* 📰"

        if not send_message(
            bot_token, bot_chatID, thread_id, starting_message, markdown=True
        ):
            logger.error(f"Failed to send starting message for {news_category}")
            return

        # Fetch the latest news headlines from the News API
        data = []
        for news_source in news_sources.keys():
            try:
                logger.info(f"Fetching news from {news_source}")
                url = f"https://newsdata.io/api/1/news?apikey={news_data_key}&category={news_category}&language=en&domain={news_source}"

                response = requests.get(url, timeout=30)
                response.raise_for_status()

                response_data = response.json()

                if "results" not in response_data:
                    logger.warning(f"No 'results' field in response from {news_source}")
                    continue

                for article in response_data["results"]:
                    if article.get("link") and article.get("title"):
                        data.append(article)

            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to fetch news from {news_source}: {e}")
                continue
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response from {news_source}: {e}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error fetching from {news_source}: {e}")
                continue

        # Filter out already sent messages using database
        data = [
            article
            for article in data
            if article.get("title") and not is_message_sent(article.get("title"))
        ]

        if len(data) == 0:
            no_news_msg = f"No new news from {news_sources[list(news_sources.keys())[0]]['source_name']} today  (ಠ  ʖ ಠ)"
            send_message(bot_token, bot_chatID, thread_id, no_news_msg)
        else:
            source_name = news_sources[list(news_sources.keys())[0]]["source_name"]
            send_message(bot_token, bot_chatID, thread_id, f"News from {source_name}: ")

            processed_count = 0
            for article in data:
                try:
                    article_url = article["link"]
                    news_container = news_sources[list(news_sources.keys())[0]][
                        "news_container"
                    ]
                    classes_to_avoid = news_sources[list(news_sources.keys())[0]][
                        "classes_to_avoid"
                    ]

                    content = extract_content(
                        news_container,
                        classes_to_avoid,
                        tags_to_avoid,
                        article_url,
                        list(news_sources.keys())[0],
                    )
                    if not content:
                        logger.warning(f"Failed to extract content from: {article_url}")
                        continue

                    summary = summarize_text(textgear_api_key, content)
                    if not summary:
                        logger.warning(
                            f"Failed to summarize article: {article['title']}"
                        )
                        continue

                    message = f"{article['title']}\n\n{summary}\n\n{article_url}"
                    logger.info(f"Sending article: {article['title']}")

                    if send_message(bot_token, bot_chatID, thread_id, message):
                        record_sent_message(
                            article["title"],
                            article_url,
                            news_category,
                            list(news_sources.keys())[0],
                        )
                        processed_count += 1
                    else:
                        logger.error(
                            f"Failed to send message for article: {article['title']}"
                        )

                    # Add small delay to avoid rate limiting
                    time.sleep(1)

                except Exception as e:
                    logger.error(
                        f"Error processing article {article.get('title', 'Unknown')}: {e}"
                    )
                    continue

            logger.info(
                f"Successfully processed {processed_count} articles for {news_category}"
            )

    except Exception as e:
        logger.error(f"Critical error in send_news_category for {news_category}: {e}")
        # Send error notification to admin
        error_msg = f"❌ Error processing {news_category} news: {str(e)}"
        send_message(bot_token, bot_chatID, thread_id, error_msg)


def extract_content(
    news_container: Dict,
    classes_to_avoid: List[str],
    tags_to_avoid: List[str],
    url: str,
    news_source: str,
) -> Optional[str]:
    """Extract article content from webpage with error handling."""
    try:
        element_type = next(iter(news_container))  # Get the first (and only) key
        element_class = news_container[element_type]  # Get the corresponding value

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Find the element with corresponding class
        news_content = soup.find(element_type, class_=element_class)
        if not news_content:
            logger.warning(
                f"Could not find content container for {news_source} at {url}"
            )
            return None

        # Remove unwanted elements based on their class names
        for class_name in classes_to_avoid:
            elements_to_remove = news_content.find_all(class_=class_name)
            for element in elements_to_remove:
                element.decompose()

        news_text = news_content.findAll(string=True)
        news_text = [text for text in news_text if tag_visible(tags_to_avoid, text)]
        content = " ".join(t.strip() for t in news_text if t.strip())

        if len(content) < 100:  # Minimum content length check
            logger.warning(f"Content too short ({len(content)} chars) for {url}")
            return None

        logger.debug(f"Extracted {len(content)} characters from {news_source}")
        return content

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch article from {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error extracting content from {url}: {e}")
        return None


def summarize_text(textgear_api_key: str, text: str) -> Optional[str]:
    """Summarize text using TextGear API with error handling and retry logic."""
    if not text or len(text) < 100:
        logger.warning("Text too short for summarization")
        return None

    # Truncate text if too long (API limits)
    max_text_length = 5000
    if len(text) > max_text_length:
        text = text[:max_text_length] + "..."
        logger.info(f"Truncated text to {max_text_length} characters")

    for attempt in range(3):  # Retry up to 3 times
        try:
            url = "https://api.textgears.com/summarize"
            payload = {"key": textgear_api_key, "text": text}

            response = requests.post(url, data=payload, timeout=30)
            response.raise_for_status()

            data = response.json()

            if "response" not in data or "summary" not in data["response"]:
                logger.warning("Invalid response structure from TextGear API")
                return None

            summary_list = data["response"]["summary"]
            if not summary_list:
                logger.warning("Empty summary received from TextGear API")
                return None

            summary = "\n".join(summary_list)
            logger.debug(f"Generated summary of {len(summary)} characters")
            return summary

        except requests.exceptions.RequestException as e:
            logger.error(f"TextGear API request failed (attempt {attempt + 1}): {e}")
            if attempt < 2:  # Don't sleep on the last attempt
                time.sleep(2**attempt)  # Exponential backoff
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse TextGear API response: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in summarization: {e}")
            return None

    logger.error("Failed to get summary after 3 attempts")
    return None


def send_message(
    bot_token: str,
    bot_chatID: str,
    thread_id: str,
    message: str,
    markdown: bool = False,
) -> bool:
    """Send message to Telegram with error handling and retry logic."""
    if not message or not message.strip():
        logger.warning("Empty message, skipping send")
        return False

    # Split long messages if needed (Telegram limit is 4096 characters)
    max_length = 4000  # Leave some buffer
    if len(message) > max_length:
        logger.info(f"Message too long ({len(message)} chars), splitting")
        parts = [
            message[i : i + max_length] for i in range(0, len(message), max_length)
        ]
        for i, part in enumerate(parts):
            success = send_message(
                bot_token, bot_chatID, thread_id, part, markdown and i == 0
            )
            if not success:
                return False
            time.sleep(0.5)  # Small delay between parts
        return True

    for attempt in range(3):  # Retry up to 3 times
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

            payload = {
                "chat_id": bot_chatID,
                "text": message,
                "message_thread_id": thread_id,
                "reply_to_message_id": thread_id,
            }

            if markdown:
                payload["parse_mode"] = "MarkdownV2"

            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()

            result = response.json()
            if result.get("ok"):
                logger.debug(f"Message sent successfully (length: {len(message)})")
                return True
            else:
                logger.error(
                    f"Telegram API error: {result.get('description', 'Unknown error')}"
                )
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send message (attempt {attempt + 1}): {e}")
            if attempt < 2:
                time.sleep(2**attempt)  # Exponential backoff
        except Exception as e:
            logger.error(f"Unexpected error sending message: {e}")
            return False

    logger.error("Failed to send message after 3 attempts")
    return False


def tag_visible(avoided_tags, element):
    """Filter out unwanted tags and comments."""
    if element.parent.name in avoided_tags or isinstance(element, Comment):
        return False
    return True


def pin_last_message(bot_token: str, bot_chatID: str):
    """Pin the last message in the chat."""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates?offset=-1"
        response = requests.get(url)
        response.raise_for_status()

        result = response.json()
        if result.get("result"):
            last_message_id = result["result"][0]["message"]["message_id"]

            url = f"https://api.telegram.org/bot{bot_token}/pinChatMessage"
            payload = {
                "chat_id": bot_chatID,
                "message_id": last_message_id,
            }

            pin_response = requests.post(url, json=payload)
            pin_response.raise_for_status()

            logger.info(f"Pinned message {last_message_id}")
            return True

    except Exception as e:
        logger.error(f"Error pinning message: {e}")
        return False


def validate_environment() -> bool:
    """Validate that all required environment variables are set."""
    required_vars = [
        "BOT_TOKEN",
        "BOT_CHAT_ID",
        "NEWS_DATA_KEY",
        "TEXT_GEAR_KEY",
        "TECHNOLOGY_THREAD_ID",
        "SCIENCE_THREAD_ID",
        "SPORTS_THREAD_ID",
        "BUSINESS_THREAD_ID",
    ]

    missing_vars = []
    for var in required_vars:
        if not os.environ.get(var):
            missing_vars.append(var)

    if missing_vars:
        logger.error(
            f"Missing required environment variables: {', '.join(missing_vars)}"
        )
        return False

    logger.info("All required environment variables are set")
    return True


def fetch_news_articles(
    news_data_key: str, category: str, sources: List[str]
) -> List[Dict]:
    """Fetch news articles from multiple sources."""
    articles = []

    for source in sources:
        try:
            logger.info(f"Fetching {category} news from {source}")
            url = f"https://newsdata.io/api/1/news?apikey={news_data_key}&category={category}&language=en&domain={source}"

            response = requests.get(url, timeout=30)
            response.raise_for_status()

            data = response.json()

            if "results" in data:
                for article in data["results"]:
                    if article.get("link") and article.get("title"):
                        article["source_key"] = source
                        articles.append(article)

        except Exception as e:
            logger.error(f"Error fetching from {source}: {e}")
            continue

    return articles


def process_article(
    article: Dict, source_config: Dict, textgear_api_key: str, tags_to_avoid: List[str]
) -> Optional[Dict]:
    """Process a single article: extract content and generate summary."""
    try:
        content = extract_content(
            source_config["news_container"],
            source_config["classes_to_avoid"],
            tags_to_avoid,
            article["link"],
            article["source_key"],
        )

        if not content:
            return None

        summary = summarize_text(textgear_api_key, content)
        if not summary:
            return None

        return {
            "title": article["title"],
            "url": article["link"],
            "summary": summary,
            "source": source_config["source_name"],
            "source_key": article["source_key"],
        }

    except Exception as e:
        logger.error(f"Error processing article {article.get('title')}: {e}")
        return None
