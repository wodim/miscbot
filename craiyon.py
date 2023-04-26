from time import sleep

from telegram import Update
from telegram.ext import CallbackContext
from wand.image import Image

from utils import create_gallery, logger, get_command_args, get_url, image_from_b64, requests_session


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

    while True:
        r = requests_session.post('https://api.craiyon.com/v3', json={
            'prompt': prompt,
            'negative_prompt': 'low quality',
            'model': 'none',
            'version': '35s5hfwn9n78gb06',
            'token': None,
        })
        if r.ok:
            json = r.json()
            images = [Image(blob=get_url(f'https://img.craiyon.com/{path}')) for path in json['images']]
            next_prompt = json['next_prompt'] if not json['next_prompt'].startswith('Sorry,') else None
            update.message.reply_photo(create_gallery(images), caption=f'Suggestion:\n{next_prompt}')
            break
        logger.info('craiyon request failed: "%s". retrying...', r.text)
        sleep(1)

    progress_msg.delete()


def command_dalle(update: Update, _: CallbackContext) -> None:
    """requests images for a specific prompt from dalle mini"""
    prompt = get_command_args(update, use_quote=True)
    if not prompt:
        update.message.reply_text('Must specify or quote a prompt.')
        return

    progress_msg = update.message.reply_text(
        f'Asking DALL·E mini to generate images for prompt "{prompt[:4000]}"…',
        quote=False
    )

    while True:
        r = requests_session.post('https://bf.dallemini.ai/generate', json={'prompt': prompt})
        if r.ok:
            images = [Image(blob=image_from_b64('data:image/jpeg;base64,' + blob)) for blob in r.json()['images']]
            update.message.reply_photo(create_gallery(images))
            break
        logger.info('dalle request failed. retrying...')
        sleep(1)

    progress_msg.delete()
