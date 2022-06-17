from base64 import b64decode
from itertools import count
from math import floor
from time import sleep

import requests
from telegram import Update
from telegram.ext import CallbackContext
from wand.image import Image

from utils import logger, get_command_args


DALLE_SIZE = 256
def command_dalle(update: Update, _: CallbackContext) -> None:
    """requests images for a specific prompt from dall-e mini"""
    prompt = get_command_args(update, use_quote=True)
    if not prompt:
        update.message.reply_text('Must specify or quote a prompt.')
        return

    progress_msg = update.message.reply_text(
        f'Asking DALL·E mini to generate images for prompt "{prompt}"…',
        quote=False
    )

    for _ in count():
        r = requests.post('https://bf.dallemini.ai/generate', json={'prompt': prompt})
        if r.ok:
            try:
                with Image(width=DALLE_SIZE * 3, height=DALLE_SIZE * 3) as canvas:
                    for i, image_blob in enumerate(r.json()['images']):
                        with Image(blob=b64decode(image_blob)) as image:
                            left = (i % 3 + 1) * DALLE_SIZE - DALLE_SIZE
                            top = floor(i / 3) * DALLE_SIZE
                            canvas.composite(image, left=left, top=top)
                    update.message.reply_photo(canvas.make_blob(format='jpeg'))
                break
            except Exception as exc:
                logger.info('dall-e mini request failed to send: %s. retrying...', exc)
        logger.info('dall-e mini request for failed. retrying...')
        sleep(1)

    progress_msg.delete()
