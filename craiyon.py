from base64 import b64decode
from itertools import count
from math import floor
from time import sleep

import requests
from telegram import Update
from telegram.ext import CallbackContext
from wand.image import Image

from utils import logger, get_command_args, get_url


CRAIYON_SIZE = 1024
def command_craiyon(update: Update, _: CallbackContext) -> None:
    """requests images for a specific prompt from craiyon"""
    prompt = get_command_args(update, use_quote=True)
    if not prompt:
        update.message.reply_text('Must specify or quote a prompt.')
        return

    progress_msg = update.message.reply_text(
        f'Asking Craiyon to generate images for prompt "{prompt[:4000]}"…',
        quote=False
    )

    for _ in count():
        r = requests.post('https://api.craiyon.com/draw', json={
            'prompt': prompt,
            'version': '35s5hfwn9n78gb06',
            'token': None,
        })
        if r.ok:
            images = [get_url(f'https://img.craiyon.com/{path}') for path in r.json()['images']]
            try:
                with Image(width=CRAIYON_SIZE * 3, height=CRAIYON_SIZE * 3) as canvas:
                    for i, image_blob in enumerate(images):
                        with Image(blob=image_blob) as image:
                            left = (i % 3 + 1) * CRAIYON_SIZE - CRAIYON_SIZE
                            top = floor(i / 3) * CRAIYON_SIZE
                            canvas.composite(image, left=left, top=top)
                    update.message.reply_photo(canvas.make_blob(format='jpeg'))
                break
            except Exception as exc:
                logger.info('craiyon request failed to send: %s. retrying...', exc)
        logger.info('craiyon request for failed. retrying...')
        sleep(1)

    progress_msg.delete()
