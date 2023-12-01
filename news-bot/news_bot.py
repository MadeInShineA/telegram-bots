
import requests
import json
from bs4 import BeautifulSoup
from bs4.element import Comment
from dotenv import load_dotenv
import datetime
import os

# Define the /news command handler


# def send_news(bot_token, bot_chatID, thread_id, news_data_key, textgear_api_key, source_content_dict, avoided_tags, avoided_classes_dict, news_type):
def send_news_category(bot_token, bot_chatID, thread_id, textgear_api_key, news_category, news_sources, tags_to_avoid):
    sent_messages = load_sent_messages()
    today = datetime.date.today().strftime('%B %d, %Y')
    starting_message = f'📰 *{today}\'s {news_category.capitalize()} News* 📰'
    send_message(bot_token, bot_chatID, thread_id, starting_message, markdown=True)
    #pin_last_message()
    # Fetch the latest news headlines from the News API
    data = []
    for news_source in news_sources.keys():
        url = f'https://newsdata.io/api/1/news?apikey={news_data_key}&category={news_category}&language=en&domain={news_source}'
        responses = requests.get(url)
        responses = json.loads(responses.text)

        for response in responses['results']:
            data.append(response)

        data = [data_with_link for data_with_link in data if
                data_with_link.get('link') and data_with_link.get('title') not in sent_messages]

        if len(data) == 0:
            send_message(bot_token, bot_chatID, thread_id, f'No news from {news_sources[news_source]["source_name"]} today  (ಠ  ʖ ಠ)')
        else:
            send_message(bot_token, bot_chatID, thread_id, f'News from {news_sources[news_source]["source_name"]} : ')
            for article in data:
                url = article['link']
                news_container = news_sources[news_source]['news_container']
                classes_to_avoid = news_sources[news_source]['classes_to_avoid']
                content = extract_content(news_container, classes_to_avoid, tags_to_avoid, url, news_source)
                if not content:
                    continue
                summary = summarize_text(textgear_api_key, content)
                if not summary:
                    continue
                message = f'{article["title"]}\n\n{summary}\n\n{url}'
                print(message)
                send_message(bot_token, bot_chatID, thread_id, message)
                write_sent_message(sent_messages, article['title'])


def load_sent_messages():

    with open('sent_messages.json', 'r') as f:
        sent_messages = json.load(f)
        f.close()

    return sent_messages


def pin_last_message():

    url = f'https://api.telegram.org/bot{bot_token}/getUpdates?offset=-1'
    last_message_id = requests.get(url).json()['result'][0]['message']['message_id']

    url = f'https://api.telegram.org/bot{bot_token}/pinChatMessage'

    payload = {
        'chat_id': bot_chatID,
        'message_id': last_message_id,
    }
    requests.post(url, payload)

def write_sent_message(sent_messages,title):
    sent_messages.append(title)
    with open('sent_messages.json','w') as f:
        json.dump(sent_messages, f)


# Define the function to extract the content of an article
def extract_content(news_container, classes_to_avoid, tags_to_avoid, url, news_source):
    element_type = next(iter(news_container))  # Get the first (and only) key
    element_class = news_container[element_type]  # Get the corresponding value

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58. Safari/537.3'
    }
    website = requests.get(url, headers=headers)
    soup = BeautifulSoup(website.text, 'html.parser')

    # Find the element with corresponding class
    news_content = soup.find(element_type, class_=element_class)
    if not news_content:
        return None
    # Remove unwanted elements based on their class names
    for class_name in classes_to_avoid:
        elements_to_remove = news_content.find_all(class_=class_name)
        for element in elements_to_remove:
            element.decompose()

    news_text = news_content.findAll(string=True)
    news_text = [text for text in news_text if tag_visible(tags_to_avoid, text)]
    content = u' '.join(t.strip() for t in news_text)

    return content


# Define the function to summarize text using the TextGear API
def summarize_text(textgear_api_key, text):
    url = f'https://api.textgears.com/summarize?key={textgear_api_key}&text={text}'
    response = requests.post(url)
    if response.status_code == 200:
        data = json.loads(response.text)
        return '\n'.join(data['response']['summary'])


# Define the function to send a message via the Telegram Bot API
def send_message(bot_token, bot_chatID, thread_id, message, markdown=False):
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'

    payload = {
        'chat_id': bot_chatID,
        'text': message,
        'message_thread_id': thread_id,
        'reply_to_message_id': thread_id,
    }

    if markdown:
        payload['parse_mode'] = 'MarkdownV2'
    requests.post(url, json=payload)


# Define the function to filter out unwanted tags and comments
def tag_visible(avoided_tags, element):
    if element.parent.name in avoided_tags or isinstance(element, Comment):
        return False
    return True

if __name__ == '__main__':

    load_dotenv()

    # Set up the Telegram Bot API key and chat ID
    bot_token = os.environ.get('BOT_TOKEN')
    bot_chatID = os.environ.get('BOT_CHAT_ID')

    # Set up the NewsData API
    news_data_key = os.environ.get('NEWS_DATA_KEY')

    # Set up the TextGear API
    textgear_api_key = os.environ.get('TEXT_GEAR_KEY')

    # TODO Restructure the data to incorporate the news type thread ID and the avoided class per news source
    # Array of the news categories containing the news sources and their corresponding news content element
    news_categories_dict = {
        'technology': {
            'news_sources': {
                'sciencealert': {
                    'source_name': 'Science Alert',
                    'news_container': {'div': 'post-content'},
                    'classes_to_avoid': []
                },
                'phys': {
                    'source_name': 'Phys.org',
                    'news_container': {'div': 'article-main'},
                    'classes_to_avoid': ['article-main__more', 'd-inline-block', 'd-none']
                },
                'wired': {
                    'source_name': 'Wired',
                    'news_container': {'div': 'body__inner-container'},
                    'classes_to_avoid': []
                },
                'techcrunch': {
                    'source_name': 'TechCrunch',
                    'news_container': {'div': 'article-content'},
                    'classes_to_avoid': ['embed', 'wp-embedded-content', 'piano-inline-promo', 'tp-container-inner']
                },
            },
            'thread_id': os.environ.get('TECHNOLOGY_THREAD_ID')
        },
        'science': {
            'news_sources': {
                'sciencealert': {
                    'source_name': 'Science Alert',
                    'news_container': {'div': 'post-content'},
                    'classes_to_avoid': []
                },
                'phys': {
                    'source_name': 'Phys.org',
                    'news_container': {'div': 'article-main'},
                    'classes_to_avoid': ['article-main__more', 'd-inline-block', 'd-none']
                },
                'wired': {
                    'source_name': 'Wired',
                    'news_container': {'div': 'body__inner-container'},
                    'classes_to_avoid': []
                },
                'techcrunch': {
                    'source_name': 'TechCrunch',
                    'news_container': {'div': 'article-content'},
                    'classes_to_avoid': ['embed', 'wp-embedded-content', 'piano-inline-promo', 'tp-container-inner']
                },
            },
            'thread_id': os.environ.get('SCIENCE_THREAD_ID'),
        },
        'sports': {
            'news_sources': {
                'espn': {
                    'source_name': 'ESPN',
                    'news_container': {'div': 'article-body'},
                    'classes_to_avoid': ['article-meta', 'content-reactions', 'editorial']
                },
            },
            'thread_id': os.environ.get('SPORTS_THREAD_ID'),
        },
        'business': {
            'news_sources': {
                'cnbc': {
                    'source_name': 'CNBC',
                    'news_container': {'div': 'ArticleBody-articleBody'},
                    'classes_to_avoid': ['RelatedContent-relatedContent', 'RelatedQuotes-relatedQuotes', 'InlineImage-imageEmbed', 'InlineImage-wrapper', 'QuoteInBody-inlineButton']
                },
            },
            'thread_id': os.environ.get('BUSINESS_THREAD_ID'),
        },
    }

    # Array of the HTML tags to avoid
    tags_to_avoid = ['style', 'script', 'head', 'title', 'meta', 'figcaption', '[document]', 'sub']

    for news_category in news_categories_dict.keys():
        thread_id = news_categories_dict[news_category]['thread_id']
        news_sources = news_categories_dict[news_category]['news_sources']
        send_news_category(bot_token, bot_chatID, thread_id, textgear_api_key, news_category, news_sources, tags_to_avoid)