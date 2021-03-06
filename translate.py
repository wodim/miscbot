import os
import random
import re
import subprocess

from telegram import ChatAction, Update
from telegram.constants import MAX_MESSAGE_LENGTH, PARSEMODE_HTML
from telegram.ext import CallbackContext


from utils import (_config, clean_up, ellipsis, get_command_args,
                   get_random_string, logger, remove_command)


def sub_translate(text, languages):
    """translate, or else"""
    for _ in range(int(_config('translate_retries'))):
        logger.info('Translating %s "%s"', '->'.join(languages), ellipsis(text, 6))
        try:
            if os.path.exists('translate-ng'):
                filename = 'translate_tmp_' + get_random_string(16) + '.txt'
                with open(filename, 'wt', newline='', encoding='utf8') as fp:
                    print(clean_up(text), file=fp)
                subprocess.call(['./translate-ng', filename, ','.join(languages)])
                with open(filename, 'rt', newline='', encoding='utf8') as fp:
                    results = fp.read().split('__TRANSLATE_NG_SENTINEL__')[:-1]
                it = iter(results)
                os.remove(filename)
                return results[-2], list(zip(it, it))
            raise RuntimeError("can't translate: helper program does not exist")
        except:
            pass


RX_MULTI_LANG = re.compile(r'^([a-z]{2})\-([a-z]{2})(\s|$)', re.IGNORECASE)
RX_SINGLE_LANG = re.compile(r'^([a-z]{2})(\s|$)', re.IGNORECASE)
TRANSLATE_USAGE = """<b>Usage</b>
/translate en-zh <i>Text to translate</i>
/translate de <i>Text to translate</i> (source language is detected automatically)
/translate <i>Text to translate</i> (source language is detected automatically; target defaults to <b>%s</b>)
<i>Text to translate</i> can be omitted if you quote another message.

<b>Supported languages</b>
"""
def command_translate(update: Update, context: CallbackContext) -> None:
    """handles the /translate command."""
    text = get_command_args(update, use_quote=update.message.text.startswith('/translate'))

    lang_from, lang_to = 'auto', _config('translate_default_language')
    if not context.args:
        # there are no parameters to the command so use default options
        pass
    elif matches := RX_MULTI_LANG.match(remove_command(update.message.text)):
        lang_from, lang_to = matches[1], matches[2]
        text = RX_MULTI_LANG.sub('', text)
    elif matches := RX_SINGLE_LANG.match(remove_command(update.message.text)):
        lang_from, lang_to = 'auto', matches[1]
        text = RX_SINGLE_LANG.sub('', text)

    if lang_from == lang_to:
        update.message.reply_text("Source and target languages can't be the same.")
        return

    all_languages = sorted([x.strip() for x in _config('translate_all_languages').split(',')])

    if lang_from not in all_languages + ['auto']:
        update.message.reply_text(f'Invalid source language "{lang_from}" provided.')
        return
    if lang_to not in all_languages:
        update.message.reply_text(f'Invalid target language "{lang_to}" provided.')
        return

    if not text or not text.strip():
        update.message.reply_text((TRANSLATE_USAGE % _config('translate_default_language')
                                   + ', '.join(all_languages)),
                                  parse_mode=PARSEMODE_HTML)
        return

    if text.startswith('. '):
        text = text[2:]

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.TYPING)

    try:
        translation, _ = sub_translate(text, [lang_from, lang_to])
    except Exception as exc:
        update.message.reply_text('Error: ' + str(exc))
        return
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.TYPING)

    update.message.reply_text(ellipsis(translation, MAX_MESSAGE_LENGTH), disable_web_page_preview=True)


def get_scramble_languages() -> list[str]:
    """returns a random list of languages to be used by the translator to
    scramble text"""
    languages = [x.strip() for x in _config('translate_scrambler_languages').split(',')]
    random.shuffle(languages)
    return (['auto'] +
            languages[:int(_config('translate_scrambler_count'))] +
            [_config('translate_default_language')])


def command_scramble(update: Update, context: CallbackContext) -> None:
    """handles the /scramble command."""
    text = get_command_args(update, use_quote=update.message.text.startswith('/scramble'))

    if not text:
        update.message.reply_text('Scramble what? Type something or quote a message.')
        return

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.TYPING)

    try:
        scrambled, _ = sub_translate(text, get_scramble_languages())
    except Exception as exc:
        update.message.reply_text('Error: ' + str(exc))
        return
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.TYPING)

    update.message.reply_text(ellipsis(scrambled, MAX_MESSAGE_LENGTH), disable_web_page_preview=True)
