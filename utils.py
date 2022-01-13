import configparser
import logging
import random
import re
import string


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


def is_admin(user_id: int) -> dict:
    if admins := _config('admins'):
        return user_id in [int(x.strip()) for x in admins.split(',')]
    return False


def get_random_string(l):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=l))
