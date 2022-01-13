import html
import os
import pickle
import pprint
import random
import re
import signal
import threading

from telegram import Bot, ChatAction, Update
from telegram.constants import PARSEMODE_HTML
from telegram.ext import CallbackContext, CommandHandler, Filters, MessageHandler, Updater
from telegram.utils.request import Request
from wand.image import Image

from actions import Actions
from commands_text import command_fortune, command_tip, command_oiga
from message_history import MessageHistory
from translate import TranslateWorkerThread, translate
from utils import (_config, ellipsis, get_command_args, get_random_string,
                   get_relays, get_username, is_admin, logger, remove_command)


def sub_translate(text, languages):
    """translate, or else"""
    while True:
        logger.info('Trying to translate %s...%s "%s"', languages[0], languages[-1], ellipsis(text, 8))
        try:
            return translate(text, languages)
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
    """handles the /translate command. somewhat complex because of all the cases
    it needs to handle: omitting target or both languages, translating quoted
    messages..."""
    text = get_command_args(update)

    lang_from, lang_to = 'auto', _config('default_language')
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

    all_languages = sorted([x.strip() for x in _config('all_languages').split(',')])

    if lang_from not in all_languages + ['auto']:
        update.message.reply_text('Invalid source language "%s" provided.' % lang_from)
        return
    if lang_to not in all_languages:
        update.message.reply_text('Invalid target language "%s" provided.' % lang_to)
        return

    if not text or not text.strip():
        update.message.reply_text((TRANSLATE_USAGE % _config('default_language')
                                   + ', '.join(all_languages)),
                                  parse_mode=PARSEMODE_HTML)
        return

    actions.append(update.message.chat_id, ChatAction.TYPING)

    try:
        translation, _ = sub_translate(text, [lang_from, lang_to])
    except Exception as exc:
        update.message.reply_text('Error: ' + str(exc))
        return
    finally:
        actions.remove(update.message.chat_id, ChatAction.TYPING)

    if update.message.reply_to_message:
        update.message.reply_to_message.reply_text(ellipsis(translation, 4000))
    else:
        update.message.reply_text(ellipsis(translation, 4000))


def get_scramble_languages() -> list[str]:
    """returns a random list of languages to be used by the translator to
    scramble text"""
    languages = [x.strip() for x in _config('scrambler_languages').split(',')]
    random.shuffle(languages)
    return (['auto'] +
            languages[:int(_config('scrambler_languages_count'))] +
            [_config('default_language')])


def command_scramble(update: Update, _: CallbackContext) -> None:
    """handles the /scramble command."""
    text = get_command_args(update)

    if not text:
        update.message.reply_text('Scramble what? Type or quote something.')
        return

    actions.append(update.message.chat_id, ChatAction.TYPING)

    try:
        text, _ = sub_translate(text, get_scramble_languages())
    except Exception as exc:
        update.message.reply_text('Error: ' + str(exc))
        return
    finally:
        actions.remove(update.message.chat_id, ChatAction.TYPING)

    if update.message.reply_to_message:
        update.message.reply_to_message.reply_text(ellipsis(text, 4000))
    else:
        update.message.reply_text(ellipsis(text, 4000))


distort_semaphore = threading.Semaphore(int(_config('max_concurrent_distorts')))
def sub_distort(filename: str, params: list) -> str:
    """parses the distortion parameters and distorts an image. returns
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

    with distort_semaphore:
        img = Image(filename=filename)
        w, h = img.width, img.height
        new_w = int(w * (1 + scale / 100)) if dimension in ('*', 'w') else w
        new_h = int(h * (1 + scale / 100)) if dimension in ('*', 'h') else h
        img.resize(new_w, new_h)
        img.liquid_rescale(w, h)
        img.save(filename='distorted_' + filename)
        img.destroy()
        img.close()

    return 'distorted_' + filename


def command_distort(update: Update, context: CallbackContext) -> None:
    """handles the /distort command"""

    if update.message.photo:
        filename = context.bot.get_file(update.message.photo[-1]).\
            download(custom_path=get_random_string(12) + '.jpg')
        text = update.message.caption or ''
    elif update.message.reply_to_message and len(update.message.reply_to_message.photo):
        filename = context.bot.get_file(update.message.reply_to_message.photo[-1]).\
            download(custom_path=get_random_string(12) + '.jpg')
        text = update.message.text or ''
    else:
        update.message.reply_text('Nothing to distort. Upload or quote a photo.')
        return

    actions.append(update.message.chat_id, ChatAction.UPLOAD_PHOTO)

    try:
        distorted_filename = sub_distort(filename, remove_command(text).split(' '))

        with open(distorted_filename, 'rb') as fp:
            update.message.reply_photo(fp)
    except Exception as exc:
        logger.exception('Error distorting')
        update.message.reply_text('Error distorting: %s' % exc)
        # the original is kept for troubleshooting
        return
    finally:
        actions.remove(update.message.chat_id, ChatAction.UPLOAD_PHOTO)

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

    text, trace = sub_translate(update.message.text, get_scramble_languages())

    send_relayed_message(update, context, text, trace=trace)


def command_relay_photo(update: Update, context: CallbackContext) -> None:
    """executed for every photo sent to a relayed group. distorts the photo,
    scrambles the caption if any and sends to the matching channel"""
    message_history.push(update.message)

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


def get_language_code(code):
    """formats a zz or zz-yy language code to be displayed in traces"""
    return '%4s ' % (code.split('-')[0] if '-' in code else code)


def send_relayed_message(update: Update, context: CallbackContext,
                         text=None, photo_fp=None, trace=None):
    """sends a message to a relayed channel"""
    if not message_history.can_post(update.message):
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

    message_history.add_relayed_message(update.message, message)


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
                    for relayed_message in message.relayed_messages:
                        relayed_message.delete()
                except:
                    # failed, so the message wasn't relayed yet
                    # prevent the bot from posting the relayed message
                    message_history.add_pending_removal(message)
                message_history.remove(message)
            try:
                relay_check_message.delete()
            except:
                pass


log_semaphore = threading.Semaphore()
def command_log(update: Update, _: CallbackContext) -> None:
    """logs a pickled representation of every update message to a file"""
    with log_semaphore:
        with open('log.pickle', 'ab') as fp:
            pickle.dump(update.to_dict(), fp)
            fp.write(b'\xff\x00__SENTINEL__\x00\xff')


def command_normalize(update: Update, _: CallbackContext) -> None:
    """returns the text provided after the translate module has cleaned it up"""
    if text := get_command_args(update):
        update.message.reply_text(ellipsis(TranslateWorkerThread.clean_up(text), 4000))
    else:
        update.message.reply_text('Missing parameter or quote.')


def command_restart(update: Update, _: CallbackContext) -> None:
    """restarts the bot if the user is an admin"""
    if is_admin(update.message.from_user.id):
        update.message.reply_text('Aieee!')
        with open('restart', 'wb') as fp:
            fp.write(b'%d' % update.message.chat.id)
        os.kill(os.getpid(), signal.SIGKILL)
    else:
        update.message.reply_animation(_config('error_animation'))


def command_debug(update: Update, _: CallbackContext) -> None:
    """replies with some debug info"""
    if is_admin(update.message.from_user.id):
        update.message.reply_text(actions.dump())
    else:
        update.message.reply_animation(_config('error_animation'))


def command_catchall(update: Update, _: CallbackContext) -> None:
    """handles unknown commands"""
    update.message.reply_animation(_config('error_animation'))


def command_stats(update: Update, _: CallbackContext) -> None:
    """returns the stats url for this chat"""
    if update.message.chat.type in ('group', 'supergroup'):
        update.message.reply_text(_config('stats_url').replace('CHAT_ID', str(update.message.chat_id)))
    else:
        update.message.reply_text('This is not a group.')


def command_info(update: Update, _: CallbackContext) -> None:
    """returns info about the quoted message"""
    if update.message.reply_to_message:
        update.message.reply_text(
            ('<code>%s</code>' %
             html.escape(pprint.pformat(update.message.reply_to_message.to_dict()))),
            parse_mode=PARSEMODE_HTML
        )
    else:
        update.message.reply_text('Quote a message to have its contents dumped here.')


def command_text(update: Update, _: CallbackContext) -> None:
    """returns the text of the quoted message"""
    if update.message.reply_to_message:
        update.message.reply_text(get_command_args(update))
    else:
        update.message.reply_text('Quote a message to have its text dumped here.')


if __name__ == '__main__':
    # connection pool size is workers + updater + dispatcher + job queue + main thread
    request = Request(con_pool_size=20)
    bot = Bot(_config('token'), request=request)
    updater = Updater(bot=bot, workers=16)

    message_history = MessageHistory()
    actions = Actions(bot, updater.dispatcher.job_queue)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher

    # on different commands - answer in Telegram
    dispatcher.add_handler(CommandHandler('fortune', command_fortune))
    dispatcher.add_handler(CommandHandler('tip', command_tip))
    dispatcher.add_handler(CommandHandler('oiga', command_oiga))
    dispatcher.add_handler(CommandHandler('stats', command_stats))
    dispatcher.add_handler(CommandHandler('normalize', command_normalize))
    dispatcher.add_handler(CommandHandler('restart', command_restart))
    dispatcher.add_handler(CommandHandler('debug', command_debug))
    dispatcher.add_handler(CommandHandler('info', command_info))
    dispatcher.add_handler(CommandHandler('text', command_text))
    dispatcher.add_handler(CommandHandler('translate', command_translate, run_async=True))
    dispatcher.add_handler(CommandHandler('scramble', command_scramble, run_async=True))
    dispatcher.add_handler(CommandHandler('distort', command_distort, run_async=True))
    # CommandHandlers don't work on captions, so all photos with a caption are sent to a
    # fun that will check for the command and then run command_distort if necessary
    dispatcher.add_handler(MessageHandler(Filters.caption & Filters.chat_type.group,
                                          command_distort_caption, run_async=True))

    # reply to anything that is said to me in private
    dispatcher.add_handler(MessageHandler((Filters.text | Filters.poll) & ~Filters.command & Filters.chat_type.private,
                                          command_scramble, run_async=True))
    dispatcher.add_handler(MessageHandler(Filters.photo & ~Filters.command & Filters.chat_type.private,
                                          command_distort, run_async=True))
    dispatcher.add_handler(MessageHandler(Filters.chat_type.private, command_catchall, run_async=True))

    sources = get_relays().keys()
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.text & ~Filters.command & Filters.update.message,
                                          command_relay_text, run_async=True), group=1)
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.photo & Filters.update.message,
                                          command_relay_photo, run_async=True), group=1)

    dispatcher.add_handler(MessageHandler(Filters.chat_type.groups, command_log, run_async=True))

    dispatcher.job_queue.run_repeating(cron_delete, interval=20)

    dispatcher.job_queue.run_repeating(actions.cron, interval=4)

    # Start the Bot
    updater.start_polling()

    try:
        with open('restart', 'rb') as fp:
            bot.send_animation(int(fp.read()), _config('restart_animation'))
        os.remove('restart')
    except FileNotFoundError:
        pass

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()
