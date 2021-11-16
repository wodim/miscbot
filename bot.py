import configparser
import html
import logging
import os
import random
import re

from telegram import ChatAction, Update
from telegram.constants import PARSEMODE_HTML
from telegram.ext import CallbackContext, CommandHandler, Filters, MessageHandler, Updater
from telegram.utils.helpers import escape_markdown
from wand.image import Image

from message_history import MessageHistory
from translate import translate


logging.basicConfig(format='%(asctime)s - %(name)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def _config(k: str) -> str:
    """returns a configuration value from the config file or None if it does
    not exist"""
    config = configparser.ConfigParser()
    config.read('config.ini')
    try:
        return config['bot'][k]
    except:
        return None


def ellipsis(text: str, max_: int) -> str:
    """truncates text to a max of max_ characters"""
    return text[:max_ - 1] + '…' if len(text) > max_ else text


def clean_fortune(fortune: str) -> str:
    """fixes the odd whitespace that fortunes have"""
    return fortune.replace(' \n', ' ').replace('  ', '\n').strip()


rx_command = re.compile(r'^/[a-z0-9_]+(@[a-z0-9_]+bot)?\b', re.IGNORECASE)
def remove_command(message: str) -> str:
    """removes /command or /command@my_bot from the message"""
    return rx_command.sub('', message).strip()


def get_fortune() -> str:
    """gets a fortune at random and cleans it"""
    with open('trolldb.txt', 'rt', encoding='utf8') as fp:
        fortunes = fp.read().split('%')[:-1]
    fortune = clean_fortune(random.choice(fortunes))
    return fortune


MAX_FORTUNE_RESULTS = 5
def search_fortunes(criteria: str) -> str:
    """searches the fortune database for fortunes that match the criteria and
    returns them and then None if there are more results"""
    with open('trolldb.txt', 'rt', encoding='utf8') as fp:
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


def get_username(update: Update) -> str:
    from_user = update.message.from_user.first_name
    try:
        from_user += ' ' + update.message.from_user.last_name
    except:
        pass
    return from_user


def get_relays() -> dict:
    if relays := _config('chat_relays'):
        return {int(x): (int(y), int(z)) for x, y, z in [x.strip().split('|') for x in relays.split(',')]}
    return {}


def command_fortune(update: Update, context: CallbackContext) -> None:
    """handles the /fortune command, which prints a random fortune or a list of
    a max of MAX_FORTUNE_RESULTS that match the parameter"""
    def msg(text):
        context.bot.send_message(update.message.chat_id, ellipsis(text, 4000),
                                 disable_web_page_preview=True)
    if context.args:
        if fortunes := list(search_fortunes(' '.join(context.args))):
            for fortune in fortunes:
                msg(fortune if fortune else 'Too many results. I only showed the first %d.' % MAX_FORTUNE_RESULTS)
        else:
            msg('No results.')
    else:
        msg(get_fortune())


def get_tip() -> str:
    """gets a random tip from the tips.txt file"""
    with open('tips.txt', 'rt', encoding='utf8') as fp:
        return random.choice(fp.readlines())


def command_tip(update: Update, context: CallbackContext) -> None:
    """handles the /tip command"""
    context.bot.send_message(update.message.chat_id, get_tip(),
                             disable_web_page_preview=True)


def command_help(update: Update, _: CallbackContext) -> None:
    """handles the /start and /help commands."""
    update.message.reply_text('I have nothing to say to you.')


rx_multi_lang = re.compile(r'^([a-z]{2})\-([a-z]{2})(\s|$)', re.IGNORECASE)
rx_single_lang = re.compile(r'^([a-z]{2})(\s|$)', re.IGNORECASE)
translate_usage = """Usage:
/translate es-en Text to translate
/translate en Text to translate (source language defaults to Spanish)
/translate Text to translate (source defaults to Spanish; destination defaults to English)
Text to translate can be omitted if you quote another message."""
def command_translate(update: Update, context: CallbackContext) -> None:
    """handles the /translate command. somewhat complex because of all the cases
    it needs to handle: omitting destination or both languages, translating quoted
    messages..."""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text.strip()
    elif context.args:
        text = remove_command(update.message.text)
    else:
        update.message.reply_text(translate_usage)
        return

    lang_from, lang_to = 'es', 'en'
    if not context.args:
        # there are no parameters to the command so use default options
        pass
    elif matches := rx_multi_lang.match(remove_command(update.message.text)):
        lang_from, lang_to = matches[1], matches[2]
        text = rx_multi_lang.sub('', text)
    elif matches := rx_single_lang.match(remove_command(update.message.text)):
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
        translation, _ = translate(text, [lang_from, lang_to],
                                   status_callback, (context, update.message.chat_id))
    except Exception as exc:
        update.message.reply_text('Error: ' + str(exc))
        return

    if update.message.reply_to_message:
        update.message.reply_to_message.reply_text(ellipsis(translation, 4000))
    else:
        update.message.reply_text(ellipsis(translation, 4000))


def get_scramble_languages() -> list[str]:
    """returns a random list of languages to be used by the translator to
    scramble text"""
    languages = 'ja,he,zh,hi,fi,ru,el'.split(',')
    random.shuffle(languages)
    languages = ['es'] + languages + ['es']
    return languages


def command_scramble(update: Update, context: CallbackContext) -> None:
    """handles the /scramble command."""
    if update.message.reply_to_message and update.message.reply_to_message.text:
        text = update.message.reply_to_message.text.strip()
    elif update.message.text:
        text = remove_command(update.message.text)

    if not text:
        update.message.reply_text('Scramble what? Type or quote something.')
        return

    context.bot.send_chat_action(chat_id=update.message.chat_id,
                                 action=ChatAction.TYPING)

    try:
        text, _ = translate(text, get_scramble_languages(),
                            status_callback, (context, update.message.chat_id))
    except Exception as exc:
        update.message.reply_text('Error: ' + str(exc))
        return

    if update.message.reply_to_message:
        update.message.reply_to_message.reply_text(ellipsis(text, 4000))
    else:
        update.message.reply_text(ellipsis(text, 4000))


def sub_distort(filename: str, params: list) -> str:
    """distorts an image and parses the distortion parameters. returns
    the file name of the distorted image."""
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
        scale = 25

    img = Image(filename=filename)
    w, h = img.width, img.height
    # img.resize(int(w * (1 + scale / 100)), int(h * (1 + scale / 100)))
    # img.liquid_rescale(w, h)
    new_w = int(w * (1 - scale / 100)) if dimension in ('*', 'w') else w
    new_h = int(h * (1 - scale / 100)) if dimension in ('*', 'h') else h
    img.liquid_rescale(new_w, new_h)
    img.resize(w, h)
    img.save(filename='distorted_' + filename)
    img.destroy()
    img.close()

    return 'distorted_' + filename


def command_distort(update: Update, context: CallbackContext) -> None:
    """handles the /distort command"""
    if update.message.photo:
        filename = context.bot.get_file(update.message.photo[-1]).download()
        text = update.message.caption or ''
    elif update.message.reply_to_message and len(update.message.reply_to_message.photo):
        filename = context.bot.get_file(update.message.reply_to_message.photo[-1]).download()
        text = update.message.text or ''
    else:
        update.message.reply_text('Nothing to distort. Upload or quote a photo.')
        return

    distorted_filename = sub_distort(filename, remove_command(text).split(' '))

    with open(distorted_filename, 'rb') as fp:
        update.message.reply_photo(fp)

    os.remove(filename)
    os.remove(distorted_filename)


rx_command_check = re.compile(r'^/distort(@aryan_bot)?(\s|$)', re.IGNORECASE)
def command_distort_caption(update: Update, context: CallbackContext) -> None:
    """check if a photo with caption has a distort command. if so, distorts it.
    else, it does nothing."""
    if rx_command_check.match(update.message.caption):
        command_distort(update, context)


def command_relay_text(update: Update, context: CallbackContext) -> None:
    """executed for every text message sent to a relayed group. scrambles the
    message and sends it to the matching relay channel"""
    message_history.push(update.message)

    text, trace = translate(update.message.text, get_scramble_languages())

    send_relayed_message(update, context, text, trace=trace)


def command_relay_photo(update: Update, context: CallbackContext) -> None:
    """executed for every photo sent to a relayed group. distorts the photo,
    scrambles the caption if any and sends to the matching channel"""
    message_history.push(update.message)

    filename = context.bot.get_file(update.message.photo[-1]).download()
    distorted_filename = sub_distort(filename, ['50'])

    try:
        text, trace = translate(update.message.caption, get_scramble_languages())
    except:
        text, trace = None, None

    with open(distorted_filename, 'rb') as fp:
        send_relayed_message(update, context, text, fp, trace)

    os.remove(filename)
    os.remove(distorted_filename)


def send_relayed_message(update: Update, context: CallbackContext,
                         text=None, photo_fp=None, trace=None):
    """sends a message to a relayed channel"""
    if not message_history.can_post(update.message):
        return

    relay_channel, trace_channel = get_relays()[update.message.chat_id]

    if trace_channel and trace:
        trace_text = '\n'.join(['<code>%s</code> %s' % (language, html.escape(text)) for text, language in trace])
        trace_message = context.bot.send_message(
            trace_channel,
            '<b>%s</b>\n%s' % (html.escape(get_username(update)), ellipsis(trace_text, 3900)),
            parse_mode=PARSEMODE_HTML
        )
        message_text = ('<b>%s</b> <a href="%s">[original]</a> <a href="%s">[trace]</a>\n%s' %
                        (html.escape(get_username(update)), update.message.link, trace_message.link,
                         html.escape(ellipsis(text, 900 if photo_fp else 3900))))
    else:
        message_text = ('<b>%s</b> <a href="%s">[original]</a>\n%s' %
                        (html.escape(get_username(update)), update.message.link,
                         html.escape(ellipsis(text, 900 if photo_fp else 3900))))

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

    message_history.add_relayed_message(update.message, message)


message_history = MessageHistory()


def cron_delete(_: CallbackContext) -> None:
    """gets executed periodically and tries to forward the last messages in every
    relayed group to a second channel. if any of the messages fail to forward it's
    because they were deleted from the group and must be deleted from the relay
    channel also."""
    for from_ in get_relays().keys():
        for message in message_history.get_latest(from_):
            try:
                relay_check_message = message.forward(_config('chat_relay_delete_channel'))
            except:
                try:
                    # try to remove the relayed message
                    message.relayed_message.delete()
                except:
                    # failed, so the message wasn't relayed yet
                    # prevent the bot from posting the relayed message
                    message_history.add_pending_removal(message)
                message_history.remove(message)
            try:
                relay_check_message.delete()
            except:
                pass


def status_callback(callback_args: tuple, status: str) -> None:
    context, chat_id = callback_args
    context.bot.send_chat_action(chat_id=chat_id, action=status)


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
    # CommandHandlers don't work on captions, so all photos with a caption are sent to a
    # fun that will check for the command and then run command_distort if necessary
    dispatcher.add_handler(MessageHandler(Filters.caption & Filters.chat_type.group,
                                          command_distort_caption, run_async=True))

    # reply to anything that is said to me in private
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command & Filters.chat_type.private,
                                          command_scramble, run_async=True))
    dispatcher.add_handler(MessageHandler(Filters.photo & ~Filters.command & Filters.chat_type.private,
                                          command_distort, run_async=True))

    sources = get_relays().keys()
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.text & ~Filters.command & Filters.update.message,
                                          command_relay_text, run_async=True), group=1)
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.photo & Filters.update.message,
                                          command_relay_photo, run_async=True), group=1)

    # dispatcher.add_handler(MessageHandler(Filters.text & Filters.chat_type.groups, command_check))

    dispatcher.job_queue.run_repeating(cron_delete, interval=20)

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()
