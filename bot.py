import configparser
import logging
import random
import re

from telegram import ChatAction, Update
from telegram.constants import PARSEMODE_MARKDOWN_V2
from telegram.ext import CallbackContext, CommandHandler, Filters, MessageHandler, Updater
from telegram.utils.helpers import escape_markdown
from wand.image import Image

from translate import translate


logging.basicConfig(format='%(asctime)s - %(name)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


MAX_FORTUNE_RESULTS = 5


def _config(k: str) -> str:
    config = configparser.ConfigParser()
    config.read('config.ini')
    return config['bot'][k]


def ellipsis(text: str, max_: int) -> str:
    return text[:max_ - 1] + '…' if len(text) > max_ else text


def clean_fortune(fortune: str) -> str:
    return fortune.replace(' \n', ' ').replace('  ', '\n').strip()


rx_command = re.compile(r'^/[a-z0-9_]+(@[a-z0-9_]+bot)?\s', re.IGNORECASE)
def remove_command(message: str) -> str:
    """removes /command or /command@my_bot from the message"""
    return rx_command.sub('', message)


def get_fortune() -> str:
    with open('trolldb.txt', 'rt') as fp:
        fortunes = fp.read().split('%')[:-1]
    fortune = clean_fortune(random.choice(fortunes))
    return fortune


def search_fortunes(criteria: str) -> str:
    with open('trolldb.txt', 'rt') as fp:
        fortunes = fp.read().split('%')[:-1]
    results = 0
    for fortune in fortunes:
        clean = clean_fortune(fortune)
        if criteria.lower() in clean.lower():
            results += 1
            yield clean
        if results >= MAX_FORTUNE_RESULTS:
            yield None
            return


def _e(text):
    """escapes text with markdown v2 syntax"""
    return escape_markdown(text, 2)


def get_username(update: Update) -> str:
    from_user = update.message.from_user.first_name
    try:
        from_user += ' ' + update.message.from_user.last_name
    except:
        pass
    return from_user


def get_relays() -> dict:
    if relays := _config('chat_relays'):
        return {int(x): int(y) for x, y in [x.strip().split('|') for x in relays.split(',')]}
    return {}


def command_fortune(update: Update, context: CallbackContext) -> None:
    def msg(text):
        context.bot.send_message(update.message.chat_id, ellipsis(text, 4000),
                                 disable_web_page_preview=True)
    if context.args:
        if (fortunes := list(search_fortunes(' '.join(context.args)))):
            for fortune in fortunes:
                msg(fortune if fortune else 'Too many results. I only showed the first %d.' % MAX_FORTUNE_RESULTS)
        else:
            msg('No results.')
    else:
        msg(get_fortune())


def get_tip() -> str:
    with open('tips.txt', 'rt', encoding='utf8') as fp:
        return random.choice(fp.readlines())


def command_tip(update: Update, context: CallbackContext) -> None:
    context.bot.send_message(update.message.chat_id, get_tip(),
                             disable_web_page_preview=True)


def command_help(update: Update, _: CallbackContext) -> None:
    update.message.reply_text('I have nothing to say to you.')


rx_multi_lang = re.compile(r'^([a-z]{2})\-([a-z]{2})(\s|$)', re.IGNORECASE)
rx_single_lang = re.compile(r'^([a-z]{2})(\s|$)', re.IGNORECASE)
translate_usage = """Usage:
/translate es-en Text to translate
/translate en Text to translate (source language defaults to Spanish)
/translate Text to translate (source defaults to Spanish; destination defaults to English)
Text to translate can be omitted if you quote another message."""
def command_translate(update: Update, context: CallbackContext) -> None:
    if not update.message:
        # updates that are not new messages (edited messages, etc)
        return

    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text.strip()
    elif context.args:
        text = remove_command(update.message.text)
    else:
        update.message.reply_text(translate_usage)
        return

    lang_from, lang_to = 'es', 'en'
    if not context.args:
        pass
    elif matches := rx_multi_lang.match(remove_command(update.message.text) or text):
        lang_from, lang_to = matches[1], matches[2]
        text = rx_multi_lang.sub('', text)
    elif matches := rx_single_lang.match(remove_command(update.message.text) or text):
        if context.args[0] != 'el':
            lang_from, lang_to = 'es', matches[1]
        text = rx_single_lang.sub('', text)

    if lang_from == lang_to:
        update.message.reply_text("Source and destination languages can't be the same.")
        return

    if not text.strip():
        update.message.reply_text(translate_usage)
        return

    context.bot.send_chat_action(chat_id=update.message.chat_id,
                                 action=ChatAction.TYPING)

    try:
        translation = translate(text, [lang_from, lang_to])
    except Exception as exc:
        update.message.reply_text('Error: ' + str(exc))
        return

    if update.message.reply_to_message:
        update.message.reply_to_message.reply_text(ellipsis(translation, 4000))
    else:
        update.message.reply_text(ellipsis(translation, 4000))


def sub_scramble(text: str) -> None:
    languages = 'ja,he,zh,hi,fi,ru,el,de'.split(',')
    random.shuffle(languages)
    languages = ['es'] + languages + ['es']
    return translate(text, languages)


def command_scramble(update: Update, context: CallbackContext) -> None:
    if not update.message or not update.message.text:
        # updates that are not new messages (edited messages, etc)
        return

    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text.strip()
    elif context.args:
        text = remove_command(update.message.text)
    else:
        update.message.reply_text('Scramble what? Type or quote something.')
        return

    context.bot.send_chat_action(chat_id=update.message.chat_id,
                                 action=ChatAction.TYPING)

    try:
        sub_scramble(text)
    except Exception as exc:
        update.message.reply_text('Error: ' + str(exc))

    if update.message.reply_to_message:
        update.message.reply_to_message.reply_text(ellipsis(text, 4000))
    else:
        update.message.reply_text(ellipsis(text, 4000))


def sub_distort(update: Update, context: CallbackContext, params: list) -> str:
    if update.message.photo:
        filename = context.bot.get_file(update.message.photo[-1]).download()
    elif update.message.reply_to_message and len(update.message.reply_to_message.photo):
        filename = context.bot.get_file(update.message.reply_to_message.photo[-1]).download()
    else:
        update.message.reply_text('Nothing to distort. Upload or quote a photo.')
        return

    scale = 25
    dimension = '*'
    for param in params:
        try:
            scale = int(param)
        except:
            pass
        if param in ('h', 'w'):
            dimension = param
    if not 0 < scale < 100:
        update.message.reply_text('Scale must be in the range (0, 100). Defaulting to 25.')
        scale = 25

    img = Image(filename=filename)
    w, h = img.width, img.height
    # img.resize(int(w * (1 + scale / 100)), int(h * (1 + scale / 100)))
    # img.liquid_rescale(w, h)
    new_w = int(w * (1 - scale / 100)) if dimension in ('*', 'w') else w
    new_h = int(h * (1 - scale / 100)) if dimension in ('*', 'h') else h
    img.liquid_rescale(new_w, new_h)
    img.resize(w, h)
    img.save(filename='carved_' + filename)
    img.destroy()

    return 'carved_' + filename


rx_command_check = re.compile(r'^/distort(@aryan_bot)?(\s|$)', re.IGNORECASE)
def command_distort(update: Update, context: CallbackContext) -> None:
    if not update.message:
        return

    text = update.message.text or update.message.caption
    if not rx_command_check.match(text):
        return

    filename = sub_distort(update, context, remove_command(text).split(' '))

    if update.message.reply_to_message:
        update.message.reply_to_message.reply_photo(open(filename, 'rb'))
    else:
        update.message.reply_photo(open(filename, 'rb'))


def command_relay_text(update: Update, context: CallbackContext) -> None:
    try:
        text = sub_scramble(update.message.text)
    except:
        return
    context.bot.send_message(get_relays()[update.message.chat_id],
                             '*' + _e(get_username(update)) + '*\n' + _e(ellipsis(text, 3900)),
                             parse_mode=PARSEMODE_MARKDOWN_V2, disable_web_page_preview=True)


def command_relay_photo(update: Update, context: CallbackContext) -> None:
    try:
        filename = sub_distort(update, context, ['50'])
    except:
        return
    context.bot.send_photo(get_relays()[update.message.chat_id],
                           open(filename, 'rb'),
                           caption='*' + _e(get_username(update)) + '*',
                           parse_mode=PARSEMODE_MARKDOWN_V2)


def main() -> None:
    """Start the bot."""
    # Create the Updater and pass it your bot's token.
    updater = Updater(_config('token'))

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # on different commands - answer in Telegram
    dispatcher.add_handler(CommandHandler('start', command_help))
    dispatcher.add_handler(CommandHandler('help', command_help))
    dispatcher.add_handler(CommandHandler('fortune', command_fortune))
    dispatcher.add_handler(CommandHandler('tip', command_tip))
    dispatcher.add_handler(CommandHandler('translate', command_translate, run_async=True))
    dispatcher.add_handler(CommandHandler('scramble', command_scramble, run_async=True))
    dispatcher.add_handler(CommandHandler('distort', command_distort, run_async=True))
    dispatcher.add_handler(MessageHandler(Filters.caption, command_distort, run_async=True))

    # reply to anything that is said to me in private
    dispatcher.add_handler(MessageHandler(
        Filters.text & ~Filters.command & Filters.chat_type.private, command_help
    ))

    sources = get_relays().keys()
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.text & ~Filters.command,
                                          command_relay_text, run_async=True))
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.photo,
                                          command_relay_photo, run_async=True))

    # dispatcher.add_handler(MessageHandler(Filters.text & Filters.chat_type.groups, command_check))

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()
