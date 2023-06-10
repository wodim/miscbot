import random

from telegram import Update
from telegram.ext import CallbackContext

from huggingface import HuggingFaceFormat, huggingface
from utils import _config


def command_gfpgan(update: Update, context: CallbackContext) -> None:
    """requests an upscaled image from GFPGAN"""
    huggingface(update, context, {
        'name': 'GFPGAN',
        'space': 'vicalloy-gfpgan',
        'in_format': [HuggingFaceFormat.PHOTO, 'v1.4', '4', 0],
        'out_format': HuggingFaceFormat.PHOTO,
        'hash_on_open': True,
        'fn_index': 1,
        'multiple': True,
    })


def command_caption(update: Update, context: CallbackContext) -> None:
    """takes an image and tells you what it is"""
    huggingface(update, context, {
        'name': 'Caption',
        'space': 'srddev-image-caption',
        'in_format': [HuggingFaceFormat.PHOTO],
        'out_format': HuggingFaceFormat.TEXT,
        'method': 'push',
    })


def command_sd(update: Update, context: CallbackContext) -> None:
    """requests images for a specific prompt from stable diffusion 2.1"""
    huggingface(update, context, {
        'name': 'Stable Diffusion 2.1',
        'space': 'stabilityai-stable-diffusion',
        'in_format': [HuggingFaceFormat.TEXT, _config('negative_prompt'), 9],
        'out_format': [HuggingFaceFormat.PHOTO],
        'fn_index': 2,
    })


def command_sd1(update: Update, context: CallbackContext) -> None:
    """requests images for a specific prompt from stable diffusion"""
    huggingface(update, context, {
        'name': 'Stable Diffusion 1',
        'space': 'stabilityai-stable-diffusion-1',
        'in_format': [HuggingFaceFormat.TEXT, 4, 50, 9, random.randint(0, 2147483647)],
        'out_format': [HuggingFaceFormat.PHOTO],
        'fn_index': 2,
    })


def command_anime(update: Update, context: CallbackContext) -> None:
    """turns a photo into an anime drawing using AnimeGANv2"""
    huggingface(update, context, {
        'name': 'AnimeGANv2',
        'space': 'akhaliq-animeganv2',
        'in_format': [HuggingFaceFormat.PHOTO, 'version 2 (🔺 robustness,🔻 stylization)'],
        'out_format': HuggingFaceFormat.PHOTO,
        'method': 'push',
        'multiple': True,
    })


def command_clip(update: Update, context: CallbackContext) -> None:
    """figure out a prompt to generate a similar image"""
    huggingface(update, context, {
        'name': 'CLIP Interrogator',
        'space': 'pharma-clip-interrogator',
        'in_format': [HuggingFaceFormat.PHOTO, 'ViT-L (best for Stable Diffusion 1.*)', 'best'],
        'out_format': HuggingFaceFormat.TEXT,
        'fn_index': 3,
    })


def command_falcon_start(update: Update, context: CallbackContext) -> None:
    """starts a new conversation with Falcon"""
    if update.message.chat.type == 'private':
        message = ('Started a new conversation. '
                   'You can restart the conversation by using /falcon again. '
                   'To go back to automatic distortion of text, use /distort with no parameters.')
    else:
        message = ('Started a new conversation. '
                   'Remember to quote any of my messages if you want me to reply. '
                   'You can restart the conversation by using /falcon again.')
    update.message.reply_text(message)
    context.bot_data['falcon_state'][update.message.chat.id] = []


def command_falcon_check(update: Update, context: CallbackContext) -> None:
    """checks if a message warrants a response from falcon"""
    # do nothing if in private and the bot is not in falcon mode
    if (update.message.chat.type == 'private' and
            context.bot_data['falcon_state'].get(update.message.chat.id) is None):
        return
    # do nothing if in public but they weren't quoting me - this command handler
    # only fires for replies, but they are not necessarily replies to the bot
    if (update.message.chat.type != 'private' and
            update.message.reply_to_message.from_user.id != context.bot_data['me'].id):
        return

    previous_state = context.bot_data['falcon_state'].get(update.message.chat.id)
    if update.message.chat.type != 'private' and previous_state is None:
        # this sends the "conversation started" message in groups if appropriate
        command_falcon_start(update, context)

    conversation = huggingface(update, context, {
        'name': 'Falcon',
        'space': 'huggingfaceh4-falcon-chat',
        'in_format': [HuggingFaceFormat.TEXT,
                      previous_state[:int(_config('falcon_max_answers'))] or [],
                      _config('falcon_instructions'), 0.1, 0.1],
        'out_format': HuggingFaceFormat.CHATBOT,
        'fn_index': 1,
        'quiet_progress': True,
    })

    # only save the conversation state if it didn't change during the execution of this
    # handler. this is done to avoid saving the old state if /falcon is used while
    # we were generating a response in this chat id, but it won't work if /falcon is
    # used to interrupt the first answer. still it's better than nothing.
    if previous_state == context.bot_data['falcon_state'].get(update.message.chat.id):
        context.bot_data['falcon_state'][update.message.chat.id] = conversation
