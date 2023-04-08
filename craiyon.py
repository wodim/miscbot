from itertools import count
from math import ceil, floor, sqrt
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
            images = [Image(blob=get_url(f'https://img.craiyon.com/{path}')) for path in r.json()['images']]
            size = images[0].width
            side = ceil(sqrt(len(images)))
            try:
                with Image(width=size * side, height=size * side) as canvas:
                    for i, image in enumerate(images):
                        left = (i % side + 1) * size - size
                        top = floor(i / side) * size
                        canvas.composite(image, left=left, top=top)
                        image.close()
                        image.destroy()
                    update.message.reply_photo(canvas.make_blob(format='jpeg'))
                break
            except Exception as exc:
                logger.info('craiyon request failed to send: %s. retrying...', exc)
        logger.info('craiyon request failed. retrying...')
        sleep(1)

    progress_msg.delete()
