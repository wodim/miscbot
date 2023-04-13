import datetime

from bs4 import BeautifulSoup
from telegram import ChatAction, Update
from telegram.ext import CallbackContext

from utils import _config, get_url, logger


def get_soyjak() -> str:
    image_url = None
    while not image_url:
        html = get_url('https://booru.soy/random_image/view')
        try:
            soup = BeautifulSoup(html, 'lxml')
            image_url = soup.select_one('#main_image')['src']
        except KeyError:
            # it was a video
            pass
    return f'https://booru.soy{image_url}'


def cron_soyjak(context: CallbackContext) -> None:
    if not _config('4chan_cron_chat_id'):
        return

    hour = datetime.datetime.now().astimezone().hour
    if hour % 2 == 0 or 2 < hour < 10:
        return

    try:
        image_url = get_soyjak()
        if image_url.endswith('.gif'):
            context.bot.send_animation(int(_config('4chan_cron_chat_id')), image_url)
        else:
            context.bot.send_photo(int(_config('4chan_cron_chat_id')), image_url)
    except:
        logger.exception('failed to send bihourly soyjak')


def command_soyjak(update: Update, context: CallbackContext) -> None:
    """sends you a soyjak"""
    context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_PHOTO)
    try:
        image_url = get_soyjak()
        if image_url.endswith('.gif'):
            update.message.reply_animation(image_url)
        else:
            update.message.reply_photo(image_url)
    except Exception as exc:
        update.message.reply_photo(_config('soyjak_error_photo_url'), caption=f'ACK! {str(exc)}')
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_PHOTO)
