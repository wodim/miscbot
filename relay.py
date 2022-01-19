import html
import os

from telegram import Update
from telegram.constants import PARSEMODE_HTML
from telegram.ext import CallbackContext

from commands_distort import sub_distort
from commands_translate import get_scramble_languages, sub_translate
from utils import ellipsis, get_relays, get_username


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

    filename = context.bot.get_file(update.message.photo[-1]).download()
    distorted_filename = sub_distort(filename, ['50'])

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
            '<b>%s</b>\n%s' % (html.escape(get_username(update)), ellipsis(trace_text, 3900)),
            parse_mode=PARSEMODE_HTML, disable_web_page_preview=True
        )
        message_text = ('<b>%s</b> <a href="%s">[source]</a> <a href="%s">[trace]</a>\n%s' %
                        (html.escape(get_username(update)), update.message.link, trace_message.link,
                         html.escape(ellipsis(text or '', 900 if photo_fp else 3900))))
    else:
        message_text = ('<b>%s</b> <a href="%s">[source]</a>\n%s' %
                        (html.escape(get_username(update)), update.message.link,
                         html.escape(ellipsis(text or '', 900 if photo_fp else 3900))))

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
