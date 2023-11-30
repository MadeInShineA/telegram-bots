
import requests
import json
from bs4 import BeautifulSoup
from bs4.element import Comment
from dotenv import load_dotenv
import datetime
import os

# Define the /news command handler


def news(bot_token, bot_chatID, thread_id, news_data_key, textgear_api_key, source_content_dict, avoided_tags, avoided_classes_dict, news_type):

    sent_messages = load_sent_messages()
    today = datetime.date.today().strftime('%B %d, %Y')
    starting_message = f'📰 *{today}\'s {news_type.capitalize()} News* 📰'
    send_message(bot_token, bot_chatID, thread_id, starting_message, markdown=True)
    #pin_last_message()
    # Fetch the latest news headlines from the News API
    # Uses a for loop to bypass the 10 results per request
    data = []
    source_content_dict = source_content_dict[news_type]
    for news_source in source_content_dict.keys():
        url = f'https://newsdata.io/api/1/news?apikey={news_data_key}&category={news_type}&language=en&domain={news_source}'
        responses = requests.get(url)
        responses = json.loads(responses.text)

        for response in responses['results']:
            data.append(response)

    data = [data_with_link for data_with_link in data if
            data_with_link.get('link') and data_with_link.get('title') not in sent_messages]

    if len(data) == 0:
        send_message(bot_token, bot_chatID, thread_id, 'No news today  (ಠ  ʖ ಠ)')
    for article in data:
        source = article['source_id']
        url = article['link']
        content = extract_content(source_content_dict, avoided_classes_dict, avoided_tags, url, source)
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

    url = f'https://api.telegram.org/bot{bot_token}/pinMessage'

    print(last_message_id)
    payload = {
        'chat_id': bot_chatID,
        'message_id': last_message_id,
    }
    response = requests.post(url, payload)

    print(response.text)

def write_sent_message(sent_messages,title):
    sent_messages.append(title)
    with open('sent_messages.json','w') as f:
        json.dump(sent_messages, f)


# Define the function to extract the content of an article
def extract_content(source_content_dict, avoided_classes_dict, avoided_tags, url, source):
    element_type, element_class = list(source_content_dict[source].items())[0]

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
    for class_name in avoided_classes_dict[source]:
        elements_to_remove = news_content.find_all(class_=class_name)
        for element in elements_to_remove:
            element.decompose()

    news_text = news_content.findAll(string=True)
    news_text = [text for text in news_text if tag_visible(avoided_tags, text)]
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
    bot_token = os.environ.get('BOT_TOKEN')
    bot_chatID = os.environ.get('BOT_CHAT_ID')

    # Set up the NewsData API
    news_data_key = os.environ.get('NEWS_DATA_KEY')

    # Set up the TextGear API
    textgear_api_key = os.environ.get('TEXT_GEAR_KEY')

    source_content_dict = {
        'technology': {
            'sciencealert': {'div': 'post-content'},
            'phys': {'div': 'article-main'},
            'wired': {'div': 'body__inner-container'},
            'techcrunch': {'div': 'article-content'},
        },
        'science': {
            'sciencealert': {'div': 'post-content'},
            'phys': {'div': 'article-main'},
            'wired': {'div': 'body__inner-container'},
            'techcrunch': {'div': 'article-content'},
        },
        'sports': {
            'espn': {'div': 'article-body'},
        },
        'business': {
            'cnbc': {'div': 'ArticleBody-articleBody'},
        },
    }

    avoided_tags = ['style', 'script', 'head', 'title', 'meta', 'figcaption', '[document]', 'a', 'sub']

    avoided_classes_dict = {
        'phys': ['article-main__more', 'd-inline-block', 'd-none'],
        'wired': [],
        'sciencealert': [],
        'techcrunch': ['embed', 'wp-embedded-content', 'piano-inline-promo', 'tp-container-inner'],
        'espn': ['article-meta', 'content-reactions', 'editorial'],
        'cnbc': ['RelatedContent-relatedContent']
    }

    news_type_thread_array = {
        'sports': os.environ.get('SPORTS_THREAD_ID'),
    }

    for (news_type, thread_id) in news_type_thread_array.items():
        news(bot_token, bot_chatID, thread_id, news_data_key, textgear_api_key, source_content_dict, avoided_tags, avoided_classes_dict, news_type)
