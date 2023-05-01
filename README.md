# Telegram bots

## News Bot

News Bot is a Python script that fetches the latest news headlines from various sources and summarizes them using the TextGear API. The summarized news articles are then sent to a Telegram chat using the Telegram Bot API.

### Getting Started

To use News Bot, you will need to set up the following:

- A Telegram bot and chat ID
- A NewsData API key
- A TextGear API key

Once you have obtained these credentials, you can set them as environment variables in a `.env` file in the same directory as the script. The required environment variables are:

- `BOT_TOKEN`: The token for your Telegram bot
- `BOT_CHAT_ID`: The chat ID for the Telegram chat you want to send the news articles to
- `NEWS_DATA_KEY`: Your NewsData API key
- `TEXT_GEAR_KEY`: Your TextGear API key

### Usage

To run News Bot, simply run the script using Python:

```bash
python news_bot.py
```

The script will fetch the latest news headlines from various sources and summarize them using the TextGear API. The summarized news articles will then be sent to the Telegram chat specified by `BOT_CHAT_ID`.
