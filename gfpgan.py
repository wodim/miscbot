from base64 import b64decode, b64encode
import json
import os
from time import sleep

import requests

from telegram import Update
from telegram.ext import CallbackContext
from wand.image import Image

from utils import clamp, logger, get_command_args, get_random_string


def command_gfpgan(update: Update, context: CallbackContext) -> None:
    """requests an upscaled image from gfpgan"""
    if update.message.reply_to_message and update.message.reply_to_message.photo:
        photo = update.message.reply_to_message.photo[-1]
    elif update.message.photo:
        photo = update.message.photo[-1]
    else:
        update.message.reply_text('Must send or quote a photo.')
        return

    times = 1
    param = get_command_args(update, use_quote=False)
    if param:
        try:
            times = clamp(int(param), 1, 100)
        except ValueError:
            pass

    progress_msg = update.message.reply_text(
        f'Asking GFPGAN to upscale that image (1/{times})…',
        quote=False
    )

    try:
        filename = context.bot.get_file(photo.file_id).\
            download(custom_path=get_random_string(12) + '.jpg')
    except:
        logger.exception('gfpgan: error downloading photo')
        update.message.reply_text('There was an error downloading your photo.')
        return

    with open(filename, 'rb') as fp:
        image = fp.read()
    os.remove(filename)

    with Image(blob=image) as image:
        image.transform(resize='1280x1280^')
        image = image.make_blob(format='png')

    s = requests.Session()

    for i in range(times):
        image = 'data:image/jpeg;base64,' + b64encode(image).decode('utf8')
        payload = {
            'data': [image],
            'cleared': False,
            'example_id': None,
            'session_hash': get_random_string(11),
            'action': 'predict',
        }

        context.bot_data['edits'].append_edit(progress_msg, 'Asking GFPGAN to upscale that image (%d/%d)…' % (i + 1, times))

        while True:
            try:
                r = s.post('https://hf.space/embed/jone/GFPGAN/api/queue/push/', data=json.dumps(payload))
                logger.info(r.json())
                hash = r.json()['hash']
                logger.info('received hash %s', hash)
                break
            except:
                logger.exception('initial request failed')

        while True:
            r = s.post('https://hf.space/embed/jone/GFPGAN/api/queue/status/',
                    data=json.dumps({'hash': hash}))
            try:
                response = r.json()
            except:
                logger.exception('json decode failed for this iteration')
            if response['status'] == 'COMPLETE':
                logger.info('ok complete')
                break
            if response['status'] == 'FAILED':
                update.message.reply_text('Failed.')
                return
            else:
                logger.info('waiting %s', response)
                sleep(1)

        image = b64decode(response['data']['data'][0].replace('data:image/png;base64,', ''))
        with Image(blob=image) as image:
            image.transform(resize='1280x1280>')
            image = image.make_blob(format='png')

    try:
        update.message.reply_photo(image)
    except Exception as exc:
        logger.exception('gfpgan request failed to send: %s', exc)

    progress_msg.delete()
