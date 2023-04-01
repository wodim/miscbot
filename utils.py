import configparser
from enum import Enum
import itertools
import logging
import os
import random
import re
import string
import unicodedata

from bs4 import BeautifulSoup
import emoji
import requests


logging.getLogger('apscheduler').setLevel(logging.WARNING)
format_ = '[{filename:>16}:{lineno:<4} {funcName:>16}()] {message}'
logging.basicConfig(format=format_, style='{', level=logging.INFO)
logger = logging.getLogger(__name__)


def _config(k: str = None) -> str:
    """returns a configuration value from the config file or None if it does
    not exist"""
    config = configparser.ConfigParser()
    config.read('config.ini')
    if not k:
        return config.items('bot')
    try:
        return config['bot'][k]
    except:
        return None


def ellipsis(text: str, max_: int) -> str:
    """truncates text to a max of max_ characters"""
    return text[:max_ - 1] + '…' if len(text) > max_ else text


rx_command = re.compile(r'^/[a-z0-9_]+(@[a-z0-9_]+bot)?\b', re.IGNORECASE)
def remove_command(message: str) -> str:
    """removes /command or /command@my_bot from the message"""
    return rx_command.sub('', message).strip()


def get_user_fullname(update) -> str:
    """get this user's first + last name"""
    if update.message.from_user.last_name:
        return (f'{update.message.from_user.first_name} '
                f'{update.message.from_user.last_name}')
    return update.message.from_user.first_name


def get_relays() -> dict:
    if relays := _config('chat_relays'):
        return {int(x): (int(y), int(z)) for x, y, z in [x.strip().split('|') for x in relays.split(',')]}
    return {}


def get_random_line(filename: str) -> str:
    """gets a random line from the provided file name"""
    with open(filename, 'rt', encoding='utf8') as fp:
        return random.choice(fp.readlines())


def get_command_args(update, use_quote: bool = True) -> str:
    def poll_to_text(poll):
        text = poll.question
        for option in poll.options:
            text += '\n• ' + option.text
        return text

    if use_quote and update.message.reply_to_message:
        if update.message.reply_to_message.text:
            return update.message.reply_to_message.text.strip()
        if update.message.reply_to_message.caption:
            return update.message.reply_to_message.caption.strip()
        if update.message.reply_to_message.poll:
            return poll_to_text(update.message.reply_to_message.poll)
    if update.message.poll:
        return poll_to_text(update.message.poll)
    if text := remove_command(update.message.text):
        return text
    return None


def _config_list(k, type_=str):
    """parses lists in config values"""
    if values := _config(k):
        return [type_(x.strip()) for x in values.split(',')]
    return []


def is_admin(user_id: int) -> bool:
    """is this user id in the list of admins?"""
    return user_id in _config_list('admins', int)


def send_admin_message(bot, text: str) -> None:
    """sends a message to all admins"""
    for user_id in _config_list('admins', int):
        bot.send_message(user_id, text)


def get_random_string(l):
    """get a random string of length l"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=l))


def remove_punctuation(s):
    return s.translate(str.maketrans('', '', string.punctuation + '¿¡“”«»'))


def clean_up(text):
    text = text.replace('\u200d', '').replace('\ufe0f', '')
    text = ''.join([' ' + emoji_name(x) + ' '
                    if x in emoji.EMOJI_DATA.keys() else x
                    for x in text])
    text = capitalize(text.strip())
    while '  ' in text:
        text = text.replace('  ', ' ')
    text = '\n'.join([x.strip() for x in text.split('\n')])
    return text


def emoji_name(char):
    try:
        name = unicodedata.name(char)
    except ValueError:
        return char
    if name == 'EMOJI MODIFIER FITZPATRICK TYPE-1-2':
        return 'WHITE SKINNED'
    if name == 'EMOJI MODIFIER FITZPATRICK TYPE-3':
        return 'LIGHT BROWN SKINNED'
    if name == 'EMOJI MODIFIER FITZPATRICK TYPE-4':
        return 'MODERATE BROWN SKINNED'
    if name == 'EMOJI MODIFIER FITZPATRICK TYPE-5':
        return 'DARK BROWN SKINNED'
    if name == 'EMOJI MODIFIER FITZPATRICK TYPE-6':
        return 'BLACK SKINNED'
    if name.startswith('EMOJI COMPONENT '):
        return 'WITH ' + name.replace('EMOJI COMPONENT ', '')
    if 'VARIATION SELECTOR' in name:
        return ''
    for x in ('MARK', 'SIGN'):
        if name.endswith(' ' + x):
            return name.replace(' ' + x, '')
    return name


def capitalize(text):
    upper = True
    output = ''
    for char in text.lower():
        if char.isalpha() and upper:
            output += char.upper()
            upper = False
        else:
            output += char
        if char.isdigit() and upper:
            upper = False
        elif char in set('\t\n.?!'):
            upper = True
    return output


def clamp(n, floor, ceil):
    return max(floor, min(n, ceil))


requests_session = requests.Session()
# TODO ua, etc
def get_url(url):
    logger.info('downloading %s', url)
    return requests_session.get(url).content


def get_html_element(html, element):
    soup = BeautifulSoup(html, 'lxml')
    return soup.select_one(element)


class Downloader:
    """this is a context manager that downloads files through
        http using the shared requests session"""
    def __init__(self, url):
        self.filename = f'downloader_{get_random_string(12)}.tmp'
        self.url = url

    def __enter__(self):
        self.fp = open(self.filename, 'w+b')
        logger.info('downloading %s into %s', self.url, self.filename)
        self.fp.write(get_url(self.url))
        self.fp.seek(0)
        return self.fp

    def __exit__(self, *_):
        logger.info('closing and deleting %s', self.filename)
        self.fp.close()
        os.remove(self.filename)


def repeat_words(s, l=1024):
    """repeats repeats words words in a string as much as possible,
        making sure the result is not longer than l chars"""
    # https://stackoverflow.com/a/14878621
    while '  ' in s:
        s = s.replace('  ', ' ')
    s = s.strip()
    if len(s) >= l:
        return s
    words = s.split(' ')
    return ' '.join([x for item in words for x in itertools.repeat(item, l // (len(s) + len(words)))])


class AttachmentType(Enum):
    PHOTO = 1
    VIDEO = 2
    STICKER_STATIC = 3
    STICKER_ANIMATED = 4
    VOICE_MESSAGE = 5
    VIDEO_MESSAGE = 6
    AUDIO = 7
    DOCUMENT = 8


def download_attachment(update, context, type_: AttachmentType):
    """downloads an attachment from a message or a quoted message,
        converting to the target type if necessary
        TODO needs to implement remaining types"""
    message = update.message.reply_to_message or update.message
    if type_ == AttachmentType.PHOTO:
        # TODO if video, extract first frame. if sticker, turn into jpg. etc
        if not message.photo:
            return None
        return context.bot.get_file(message.photo[-1]).\
            download(custom_path=get_random_string(12) + '.jpg')
