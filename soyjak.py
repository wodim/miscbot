import datetime

from bs4 import BeautifulSoup
from telegram import ChatAction, Update
from telegram.ext import CallbackContext

from utils import _config, get_url, get_command_args, logger


SOYJAK_TPL = 'https://booru.soy/_images/%s/image.%s'
def get_soyjak(tag: str = None) -> str:
    html = None
    for _ in range(10):
        if tag:
            html = get_url(f'https://booru.soy/post/list/{tag}/1')
        else:
            html = get_url('https://booru.soy/post/list')
        if len(html) > 10:
            break
    if len(html) < 10:
        raise ValueError('bad luck')
    soup = BeautifulSoup(html, 'lxml')
    container = soup.select_one('#Random_Gemleft')
    if not container:
        raise ValueError('404')
    if image := container.select_one('img'):
        hash_ = image['src'].split('/')[2]
        if image['src'].endswith('gif'):
            return SOYJAK_TPL % (hash_, 'gif'), 'animation'
        else:
            return SOYJAK_TPL % (hash_, 'png'), 'photo'
    if video := container.select_one('source'):
        return SOYJAK_TPL % (video['src'].split('/')[2], 'mp4'), 'video'
    raise ValueError('something came up')


def cron_soyjak(context: CallbackContext) -> None:
    if not _config('soyjak_cron_chat_id'):
        return

    hour = datetime.datetime.now().astimezone().hour
    if hour % 2 == 0 or 2 < hour < 10:
        return

    try:
        url, type_ = get_soyjak()
        if type_ == 'animation':
            context.bot.send_animation(int(_config('soyjak_cron_chat_id')), url)
        elif type_ == 'photo':
            context.bot.send_photo(int(_config('soyjak_cron_chat_id')), url)
        elif type_ == 'video':
            context.bot.send_video(int(_config('soyjak_cron_chat_id')), url)
    except:
        logger.exception('failed to send bihourly soyjak')


def command_soyjak(update: Update, context: CallbackContext) -> None:
    """sends you a soyjak"""
    context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_PHOTO)
    try:
        url, type_ = get_soyjak(get_command_args(update, use_quote=False))
    except Exception as exc:
        logger.exception('soyjak raised exception')
        update.message.reply_text(f'ACK! {str(exc)}')
        return
    for _ in range(10):
        try:
            logger.info('would post %s', (url, type_))
            if type_ == 'animation':
                update.message.reply_animation(url)
            elif type_ == 'photo':
                update.message.reply_photo(url)
            elif type_ == 'video':
                update.message.reply_video(url)
            return
        except Exception as exc:
            logger.exception('soyjak raised exception')
            #update.message.reply_text(f'ACK! {str(exc)}')
            pass
        finally:
            context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_PHOTO)
    update.message.reply_text('ACK!')
