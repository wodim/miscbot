from base64 import b64decode, b64encode
import configparser
import logging
from math import ceil, floor, sqrt
import os
import pprint
import random
import re
import string
import unicodedata

import emoji
from curl_cffi import requests
from wand.image import Image


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


requests_session = requests.Session(impersonate='chrome110',
                                    timeout=int(_config('http_timeout') or 5))
def get_url(url: str, use_tor: bool = False) -> bytes:
    timeout = int(_config('http_timeout') or 5)
    if use_tor:
        logger.info('downloading using tor: %s', url)
        proxies = dict(http='socks5://127.0.0.1:9050',
                       https='socks5://127.0.0.1:9050')
        return requests_session.get(url, proxies=proxies, timeout=timeout).content
    logger.info('downloading: %s', url)
    return requests_session.get(url, timeout=timeout).content


class Downloader:
    """this is a context manager that downloads files through
        http using the shared requests session"""
    def __init__(self, url):
        self.filename = f'downloader_{get_random_string(12)}.tmp'
        self.url = url
        self.fp = None

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


def image_from_b64(s):
    s = s.replace('data:image/png;base64,', '')
    s = s.replace('data:image/jpeg;base64,', '')
    return b64decode(s)


def image_to_b64(i):
    return 'data:image/jpeg;base64,' + b64encode(i).decode('utf-8')


def create_gallery(images):
    """creates a gallery from a list of images"""
    size = images[0].width
    side = ceil(sqrt(len(images)))
    with Image(width=size * side, height=size * side) as canvas:
        for i, image in enumerate(images):
            left = (i % side + 1) * size - size
            top = floor(i / side) * size
            canvas.composite(image, left=left, top=top)
            image.close()
            image.destroy()
        return canvas.make_blob(format='jpeg')


# this is a prettyprinter implementation that escapes non-ascii characters
# based on https://stackoverflow.com/a/10883893
class MyPrettyPrinter(pprint.PrettyPrinter):
    def format(self, object, context, maxlevels, level):
        if isinstance(object, str) and len(object) != len(object.encode()):
            return str(object.encode('utf8')), True, False
        return super().format(object, context, maxlevels, level)
