import html
import os

from telegram import Update
from telegram.constants import MAX_CAPTION_LENGTH, MAX_MESSAGE_LENGTH, PARSEMODE_HTML
from telegram.ext import CallbackContext

from distort import sub_distort, sub_invert
from translate import get_scramble_languages, sub_translate
from utils import _config, ellipsis, get_random_string, get_relays, get_user_fullname


def command_relay_text(update: Update, context: CallbackContext) -> None:
    """executed for every text message sent to a relayed group. scrambles the
    message and sends it to the matching relay channel"""
    context.bot_data['message_history'].push(update.message)

    text, trace = sub_translate(update.message.text, get_scramble_languages())

    send_relayed_message(update, context, text, trace=trace)


def command_relay_photo(update: Update, context: CallbackContext) -> None:
    """executed for every photo sent to a relayed group. distorts the photo,
    scrambles the caption if any and sends to the matching channel"""
    context.bot_data['message_history'].push(update.message)

    if update.message.sticker:
        if update.message.sticker.is_animated:
            return
        filename = context.bot.get_file(update.message.sticker.file_id).\
            download(custom_path=get_random_string(12) + '.jpg')
    else:
        filename = context.bot.get_file(update.message.photo[-1]).\
            download(custom_path=get_random_string(12) + '.jpg')
    distorted_filename = sub_distort(filename, scale=40)

    text, trace = None, None
    if update.message.caption:
        try:
            text, trace = sub_translate(update.message.caption, get_scramble_languages())
        except:
            pass

    with open(distorted_filename, 'rb') as fp:
        send_relayed_message(update, context, text, fp, trace)

    os.remove(filename)
    os.remove(distorted_filename)


def command_relay_chat_photo(update: Update, context: CallbackContext) -> None:
    """executed every time the chat picture is changed or removed in a relayed group"""
    relay_channel, trace_channel = get_relays()[update.message.chat_id]

    if update.message.delete_chat_photo:
        if trace_channel:
            context.bot.delete_chat_photo(trace_channel)
        context.bot.delete_chat_photo(relay_channel)
        return

    if update.message.new_chat_photo:
        filename = context.bot.get_file(update.message.new_chat_photo[-1]).\
            download(custom_path=get_random_string(12) + '.jpg')

    distorted_filename = sub_distort(filename, scale=40)

    if trace_channel:
        inverted_filename = sub_invert(distorted_filename)
        context.bot.set_chat_photo(trace_channel, open(inverted_filename, 'rb'))
        os.remove(inverted_filename)

    context.bot.set_chat_photo(relay_channel, open(distorted_filename, 'rb'))
    os.remove(filename)
    os.remove(distorted_filename)


def send_relayed_message(update: Update, context: CallbackContext,
                         text=None, photo_fp=None, trace=None):
    """sends a message to a relayed channel"""

    def get_language_code(code):
        """formats a zz or zz-yy language code to be displayed in traces"""
        return '%4s ' % (code.split('-')[0] if '-' in code else code)

    if not context.bot_data['message_history'].can_post(update.message):
        return

    relay_channel, trace_channel = get_relays()[update.message.chat_id]

    if trace and trace_channel and trace_channel != 0:
        trace_text = '\n'.join(['<code>%s</code>%s' % (get_language_code(language),
                                                       html.escape(text) if text else '<i>(failed)</i>')
                                for text, language in trace])
        trace_message = context.bot.send_message(
            trace_channel,
            '<b>%s</b>\n%s' % (html.escape(get_user_fullname(update)), ellipsis(trace_text, MAX_MESSAGE_LENGTH - 100)),
            parse_mode=PARSEMODE_HTML, disable_web_page_preview=True
        )
        message_text = ('<b>%s</b> <a href="%s">[source]</a> <a href="%s">[trace]</a>\n%s' %
                        (html.escape(get_user_fullname(update)), update.message.link, trace_message.link,
                         html.escape(ellipsis(text or '', MAX_CAPTION_LENGTH - 100 if photo_fp else MAX_MESSAGE_LENGTH - 100))))
    else:
        message_text = ('<b>%s</b> <a href="%s">[source]</a>\n%s' %
                        (html.escape(get_user_fullname(update)), update.message.link,
                         html.escape(ellipsis(text or '', MAX_CAPTION_LENGTH - 100 if photo_fp else MAX_MESSAGE_LENGTH - 100))))

    if photo_fp:
        message = context.bot.send_photo(
            relay_channel,
            photo_fp, caption=message_text,
            parse_mode=PARSEMODE_HTML
        )
    else:
        message = context.bot.send_message(
            relay_channel, message_text,
            parse_mode=PARSEMODE_HTML, disable_web_page_preview=True
        )

    context.bot_data['message_history'].add_relayed_message(update.message, message)


def cron_delete(context: CallbackContext) -> None:
    """gets executed periodically and tries to forward the last messages in every
    relayed group to a second channel. if any of the messages fail to forward it's
    because they were deleted from the group and must be deleted from the relay
    channel also."""
    for from_ in get_relays().keys():
        for message in context.bot_data['message_history'].get_latest(from_):
            try:
                relay_check_message = message.forward(_config('chat_relay_delete_channel'))
            except:
                try:
                    # try to remove the relayed message
                    for relayed_message in message.relayed_messages:
                        relayed_message.delete()
                except:
                    # failed, so the message wasn't relayed yet
                    # prevent the bot from posting the relayed message
                    context.bot_data['message_history'].add_pending_removal(message)
                context.bot_data['message_history'].remove(message)
            try:
                relay_check_message.delete()
            except:
                pass
