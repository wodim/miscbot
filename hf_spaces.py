import random

from telegram import Update
from telegram.constants import MAX_MESSAGE_LENGTH
from telegram.ext import CallbackContext

from huggingface import HuggingFaceFormat, huggingface
from utils import _config, get_random_string


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


def command_chatbot_start(update: Update, context: CallbackContext) -> None:
    """starts a new conversation with the chatbot"""
    if update.message.chat.type == 'private':
        message = ('Started a new conversation. '
                   'You can restart the conversation by using /chatbot again. '
                   'To go back to automatic distortion of text, use /distort with no parameters.')
    else:
        message = ('Started a new conversation. '
                   'Remember to quote any of my messages if you want me to reply. '
                   'You can restart the conversation by using /chatbot again.')
    context.bot_data['chatbot_state'][update.message.chat.id] = {
        'history': [],
        'hash': get_random_string(11),
        'message_ids': [update.message.reply_text(message).message_id],
    }


def command_chatbot_check(update: Update, context: CallbackContext) -> None:
    """checks if a message warrants a response from the chatbot"""
    state_exists = update.message.chat.id in context.bot_data['chatbot_state']

    # do nothing if in private and the bot is not in chatbot mode
    if update.message.chat.type == 'private' and not state_exists:
        return
    # do nothing if in public but they weren't quoting a chatbot response
    if update.message.chat.type != 'private' and (not hasattr(update.message, 'reply_to_message') or not state_exists or
            update.message.reply_to_message.message_id not in context.bot_data['chatbot_state'][update.message.chat.id]['message_ids']):
        return

    previous_history = context.bot_data['chatbot_state'][update.message.chat.id]['history'] if state_exists else []

    conversation = huggingface(update, context, {
        'name': 'ChatGML2-6B',
        'space': 'mikeee-chatglm2-6b-4bit',
        'in_format': [False,
                      HuggingFaceFormat.TEXT,
                      previous_history,
                      MAX_MESSAGE_LENGTH,
                      float(_config('chatbot_p')),
                      float(_config('chatbot_temperature')),
                      None,
                      None,],
        'out_format': HuggingFaceFormat.CHATBOT,
        'quiet_progress': True,
        'hash': context.bot_data['chatbot_state'][update.message.chat.id]['hash'],
    })

    # don't save history if chatbot failed
    if conversation:
        context.bot_data['chatbot_state'][update.message.chat.id]['history'] = conversation
