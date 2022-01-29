import configparser
import logging
import random
import re
import string
import unicodedata

import emoji


logging.basicConfig(format='%(asctime)s - %(name)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def _config(k: str) -> str:
    """returns a configuration value from the config file or None if it does
    not exist"""
    config = configparser.ConfigParser()
    config.read('config.ini')
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


def get_username(update) -> str:
    if update.message.from_user.last_name:
        return '%s %s' % (update.message.from_user.first_name,
                          update.message.from_user.last_name)
    return update.message.from_user.first_name


def get_relays() -> dict:
    if relays := _config('chat_relays'):
        return {int(x): (int(y), int(z)) for x, y, z in [x.strip().split('|') for x in relays.split(',')]}
    return {}


def get_random_line(filename: str) -> str:
    """gets a random line from the provided file name"""
    with open(filename, 'rt', encoding='utf8') as fp:
        return random.choice(fp.readlines())


def get_command_args(update) -> str:
    def poll_to_text(poll):
        text = poll.question
        for option in poll.options:
            text += '\n• ' + option.text
        return text

    if update.message.reply_to_message:
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


def get_admins() -> dict:
    if admins := _config('admins'):
        return [int(x.strip()) for x in admins.split(',')]
    return []


def is_admin(user_id: int) -> bool:
    return user_id in get_admins()


def send_admin_message(bot, text: str) -> None:
    """sends a message to all admins"""
    for user_id in get_admins():
        bot.send_message(user_id, text)


def get_random_string(l):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=l))


def remove_punctuation(s):
    return s.translate(str.maketrans('', '', string.punctuation + '¿¡“”«»'))


def clean_up(text):
    text = text.replace('\u200d', '').replace('\ufe0f', '')
    text = ''.join([' ' + emoji_name(x) + ' '
                    if x in emoji.UNICODE_EMOJI['en'] else x
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
