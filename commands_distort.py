import os
import re
import threading

from telegram import ChatAction, Update
from telegram.ext import CallbackContext
from wand.image import Image

from utils import _config, get_random_string, logger, remove_command


distort_semaphore = threading.Semaphore(int(_config('max_concurrent_distorts')))
def sub_distort(filename: str, params: list) -> str:
    """parses the distortion parameters and distorts an image. returns
    the file name of the distorted image."""
    scale = 25
    dimension = '*'
    for param in params:
        try:
            scale = int(param)
        except:
            pass
        if param in ('h', 'w'):
            dimension = param
    if not 0 < scale < 100:
        scale = 25

    with distort_semaphore:
        img = Image(filename=filename)
        w, h = img.width, img.height
        new_w = int(w * (1 + scale / 100)) if dimension in ('*', 'w') else w
        new_h = int(h * (1 + scale / 100)) if dimension in ('*', 'h') else h
        img.resize(new_w, new_h)
        img.liquid_rescale(w, h)
        img.save(filename='distorted_' + filename)
        img.destroy()
        img.close()

    return 'distorted_' + filename


def command_distort(update: Update, context: CallbackContext) -> None:
    """handles the /distort command"""

    if update.message.photo:
        filename = context.bot.get_file(update.message.photo[-1]).\
            download(custom_path=get_random_string(12) + '.jpg')
        text = update.message.caption or ''
    elif update.message.reply_to_message and len(update.message.reply_to_message.photo):
        filename = context.bot.get_file(update.message.reply_to_message.photo[-1]).\
            download(custom_path=get_random_string(12) + '.jpg')
        text = update.message.text or ''
    else:
        update.message.reply_text('Nothing to distort. Upload or quote a photo.')
        return

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_PHOTO)

    try:
        distorted_filename = sub_distort(filename, remove_command(text).split(' '))

        with open(distorted_filename, 'rb') as fp:
            update.message.reply_photo(fp)
    except Exception as exc:
        logger.exception('Error distorting')
        update.message.reply_text('Error distorting: %s' % exc)
        # the original is kept for troubleshooting
        return
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_PHOTO)

    os.remove(filename)
    os.remove(distorted_filename)


RX_COMMAND_CHECK = re.compile(r'^/distort(@aryan_bot)?(\s|$)', re.IGNORECASE)
def command_distort_caption(update: Update, context: CallbackContext) -> None:
    """check if a photo with caption has a distort command. if so, distorts it.
    else, it does nothing."""
    if RX_COMMAND_CHECK.match(update.message.caption):
        command_distort(update, context)
