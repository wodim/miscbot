import datetime
import html
import os
import pickle
import pprint
import signal
import threading

from nltk.corpus import stopwords
from nltk.stem import SnowballStemmer
from telegram import Bot, Update
from telegram.constants import MAX_MESSAGE_LENGTH, PARSEMODE_HTML
from telegram.ext import (CallbackContext, CommandHandler, DispatcherHandlerStop,
                          Filters, MessageHandler, TypeHandler, Updater)
from telegram.utils.request import Request

from _4chan import cron_4chan, command_thread
from calc import command_calc
from chatbot import command_chatbot
from distort import command_distort, command_distort_caption, command_invert, command_voice
from message_history import MessageHistory
from queues import Actions, Edits
from relay import (command_relay_chat_photo, command_relay_text, command_relay_photo,
                   cron_delete)
from text import command_fortune, command_tip, command_oiga
from translate import command_scramble, command_translate
from utils import (_config, capitalize, clean_up, ellipsis, get_command_args, get_relays,
                   is_admin, remove_punctuation, send_admin_message)


log_semaphore = threading.Semaphore()
def command_log(update: Update, context: CallbackContext) -> None:
    """logs a pickled representation of every update message to a file.
    then a stemmed version of every text message to another file."""
    with log_semaphore:
        with open('log.pickle', 'ab') as fp:
            pickle.dump(update.to_dict(), fp)
            try:
                fp.write(b'\xff\x00__SENTINEL__\x00\xff')
            except OSError as exc:
                send_admin_message(context.bot, str(exc))
        if hasattr(update.message, 'text') and update.message.text:
            with open(f'chat{update.message.chat.id}.txt', 'at', encoding='utf8') as fp:
                result = []
                for token in remove_punctuation(update.message.text.replace('\n', ' ').lower()).split(' '):
                    stemmed = context.bot_data['stemmer'].stem(token)
                    if stemmed not in context.bot_data['stopwords']:
                        result.append(stemmed)
                result = ' '.join([x for x in result if len(x) > 1])
                if len(result) > 0:
                    print(result + '\t' + update.message.text.replace('\n', ' '), file=fp)


def command_normalize(update: Update, _: CallbackContext) -> None:
    """returns the text provided after the translate module has cleaned it up"""
    if text := get_command_args(update):
        update.message.reply_text(ellipsis(clean_up(text), MAX_MESSAGE_LENGTH))
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
        update.message.reply_text(ellipsis(f'{actions.dump()}\n{edits.dump()}', MAX_MESSAGE_LENGTH))
    else:
        update.message.reply_animation(_config('error_animation'))


def command_flush(update: Update, _: CallbackContext) -> None:
    """flush the pending action list"""
    if is_admin(update.message.from_user.id):
        actions.flush()
        update.message.reply_text('done')
    else:
        update.message.reply_animation(_config('error_animation'))


def command_unhandled(update: Update, _: CallbackContext) -> None:
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
             ellipsis(html.escape(pprint.pformat(update.message.reply_to_message.to_dict())), MAX_MESSAGE_LENGTH)),
            parse_mode=PARSEMODE_HTML,
            disable_web_page_preview=True
        )
    else:
        update.message.reply_text('Quote a message to have its contents dumped here.')


def command_text(update: Update, _: CallbackContext) -> None:
    """returns the text of the quoted message"""
    if update.message.reply_to_message:
        if text := get_command_args(update):
            update.message.reply_text(text, disable_web_page_preview=True)
        else:
            update.message.reply_text('There is no text in that message.')
    else:
        update.message.reply_text('Quote a message to have its text dumped here.')


def callback_all(update: Update, _: CallbackContext) -> None:
    """this callback runs for all updates. raising DispatcherHandlerStop inside of
    this callback stops any other handlers from executing"""
    if not hasattr(update.message, 'from_user'):
        return
    banned_users = [int(x.strip()) for x in _config('banned_users').split(',')]
    if update.message.from_user.id in banned_users:
        raise DispatcherHandlerStop()


def command_trigger(update: Update, _: CallbackContext) -> None:
    """replies to some text triggers and stops handling"""
    if not update.message or not update.message.text:
        return
    with open('triggers.txt', 'rt', encoding='utf8') as fp:
        triggers = [x.split('\t') for x in fp.readlines()]
    for trigger, answer in triggers:
        if update.message.text.lower() == trigger.lower():
            update.message.reply_text(answer, quote=False)
            raise DispatcherHandlerStop()


def command_haiku(update: Update, _: CallbackContext) -> None:
    """detects haikus sent by group members and formats them"""
    if not update.message or not update.message.text:
        return
    text = update.message.text
    while '  ' in text:
        text = text.replace('  ', ' ')
    if text.count(' ') != 16:
        return
    parts = capitalize(text).split(' ')
    text = ' '.join(parts[:5]) + '\n' + ' '.join(parts[5:12]) + '\n' + ' '.join(parts[12:])
    if not text.endswith('.') and not text.endswith('?') and not text.endswith('!'):
        text += '.'
    update.message.reply_text(text, quote=False)


if __name__ == '__main__':
    # connection pool size is workers + updater + dispatcher + job queue + main thread
    NUM_THREADS = 16
    request = Request(con_pool_size=NUM_THREADS + 4)
    bot = Bot(_config('token'), request=request)
    updater = Updater(bot=bot, workers=NUM_THREADS)

    message_history = MessageHistory()
    actions = Actions(bot, updater.dispatcher.job_queue)
    edits = Edits(bot, updater.dispatcher.job_queue)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    dispatcher.bot_data.update({
        'message_history': message_history,
        'actions': actions,
        'edits': edits,
        'me': bot.get_me(),
        'stemmer': SnowballStemmer(_config('chatbot_language')),
    })
    dispatcher.bot_data['stopwords'] = {
        dispatcher.bot_data['stemmer'].stem(x) for x in stopwords.words(_config('chatbot_language'))
    }

    # very low group id so it runs even for banned users
    # can't run asynchronously or the log file can get corrupted
    dispatcher.add_handler(MessageHandler(Filters.chat_type.groups, command_log), group=-999)

    # relays
    sources = get_relays().keys()
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.text & ~Filters.command & Filters.update.message,
                                          command_relay_text, run_async=True), group=-20)
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & (Filters.photo | Filters.sticker) & Filters.update.message,
                                          command_relay_photo, run_async=True), group=-20)
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & (Filters.status_update.new_chat_photo |
                                                                   Filters.status_update.delete_chat_photo),
                                          command_relay_chat_photo, run_async=True), group=-20)

    # banned users
    dispatcher.add_handler(TypeHandler(Update, callback_all), group=-10)

    # automated responses
    dispatcher.add_handler(MessageHandler(Filters.text, command_trigger), group=30)

    # commands
    dispatcher.add_handler(CommandHandler('help', command_fortune), group=40)
    dispatcher.add_handler(CommandHandler('start', command_fortune), group=40)
    dispatcher.add_handler(CommandHandler('fortune', command_fortune), group=40)
    dispatcher.add_handler(CommandHandler('tip', command_tip), group=40)
    dispatcher.add_handler(CommandHandler('oiga', command_oiga), group=40)
    # this one needs to be async because we call an external program and we wait for it to die.
    dispatcher.add_handler(CommandHandler('calc', command_calc, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('stats', command_stats), group=40)
    dispatcher.add_handler(CommandHandler('normalize', command_normalize), group=40)
    dispatcher.add_handler(CommandHandler('restart', command_restart), group=40)
    dispatcher.add_handler(CommandHandler('debug', command_debug), group=40)
    dispatcher.add_handler(CommandHandler('flush', command_flush), group=40)
    dispatcher.add_handler(CommandHandler('info', command_info), group=40)
    dispatcher.add_handler(CommandHandler('text', command_text), group=40)
    dispatcher.add_handler(CommandHandler('thread', command_thread, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('translate', command_translate, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('scramble', command_scramble, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('distort', command_distort, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('voice', command_voice, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('invert', command_invert, run_async=True), group=40)
    # CommandHandlers don't work on captions, so all photos with a caption are sent to a
    # fun that will check for the command and then run command_distort if necessary
    dispatcher.add_handler(MessageHandler(Filters.caption & Filters.chat_type.group,
                                          command_distort_caption, run_async=True), group=41)

    # responses in private
    dispatcher.add_handler(MessageHandler((Filters.text | Filters.poll) & ~Filters.command & Filters.chat_type.private,
                                          command_scramble, run_async=True), group=40)
    dispatcher.add_handler(MessageHandler((Filters.photo | Filters.animation | Filters.video | Filters.sticker | Filters.voice | Filters.audio) &
                                           ~Filters.command & Filters.chat_type.private,
                                          command_distort, run_async=True), group=40)
    dispatcher.add_handler(MessageHandler(Filters.chat_type.private, command_unhandled, run_async=True), group=40)

    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command & Filters.update.message & Filters.chat_type.groups,
                                          command_chatbot, run_async=True), group=50)

    # dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command & Filters.update.message & Filters.chat_type.groups,
    #                                       command_haiku, run_async=True), group=60)

    dispatcher.job_queue.run_repeating(cron_delete, interval=20)

    dispatcher.job_queue.run_repeating(actions.cron, interval=4, name='actions').enabled = False
    dispatcher.job_queue.run_repeating(edits.cron, interval=3, name='edits').enabled = False

    first_cron = datetime.datetime.now().astimezone()
    if first_cron.hour % 2 == 0:
        first_cron += datetime.timedelta(hours=2)
    else:
        first_cron += datetime.timedelta(hours=1)
    first_cron = first_cron.replace(minute=0, second=0, microsecond=0)
    dispatcher.job_queue.run_repeating(cron_4chan, first=first_cron,
                                       interval=60 * 60 * 2)

    bot.set_my_commands([
        ('tip',          '📞'),
        ('fortune',      '🥠'),
        ('translate',    '㊙️'),
        ('scramble',     '🎲'),
        ('distort',      '🔨'),
        ('oiga',         '❗️'),
        ('stats',        '📊'),
        ('thread',       '🍀'),
        ('calc',         '🧮'),
    ])

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
