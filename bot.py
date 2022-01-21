import datetime
import html
import os
import pickle
import pprint
import signal
import threading

from telegram import Bot, Update
from telegram.constants import PARSEMODE_HTML
from telegram.ext import (CallbackContext, CommandHandler, DispatcherHandlerStop,
                          Filters, MessageHandler, TypeHandler, Updater)
from telegram.utils.request import Request

from _4chan import cron_4chan, command_thread
from actions import Actions
from commands_distort import command_distort, command_distort_caption
from commands_text import command_fortune, command_tip, command_oiga
from commands_translate import command_scramble, command_translate
from message_history import MessageHistory
from relay import command_relay_text, command_relay_photo, cron_delete
from translate import TranslateWorkerThread
from utils import (_config, ellipsis, get_command_args, get_relays,
                   is_admin, send_admin_message)


log_semaphore = threading.Semaphore()
def command_log(update: Update, context: CallbackContext) -> None:
    """logs a pickled representation of every update message to a file"""
    with log_semaphore:
        with open('log.pickle', 'ab') as fp:
            pickle.dump(update.to_dict(), fp)
            try:
                fp.write(b'\xff\x00__SENTINEL__\x00\xff')
            except OSError as exc:
                send_admin_message(context.bot, str(exc))


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
             ellipsis(html.escape(pprint.pformat(update.message.reply_to_message.to_dict())), 4000)),
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


def command_answer(update: Update, context: CallbackContext) -> None:
    """replies to some text triggers and stops handling"""
    if not update.message or not update.message.text:
        return
    with open('triggers.txt', 'rt', encoding='utf8') as fp:
        triggers = [x.split('|') for x in fp.readlines()]
    for trigger, answer in triggers:
        if update.message.text.lower() == trigger.lower():
            context.bot.send_message(update.message.chat.id, answer)
            raise DispatcherHandlerStop()


if __name__ == '__main__':
    # connection pool size is workers + updater + dispatcher + job queue + main thread
    request = Request(con_pool_size=20)
    bot = Bot(_config('token'), request=request)
    updater = Updater(bot=bot, workers=16)

    message_history = MessageHistory()
    actions = Actions(bot, updater.dispatcher.job_queue)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    dispatcher.bot_data.update({
        'message_history': message_history,
        'actions': actions,
    })

    # very low group id so it runs even for banned users
    dispatcher.add_handler(MessageHandler(Filters.chat_type.groups, command_log, run_async=True), group=-999)

    # relays
    sources = get_relays().keys()
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.text & ~Filters.command & Filters.update.message,
                                          command_relay_text, run_async=True), group=-20)
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.photo & Filters.update.message,
                                          command_relay_photo, run_async=True), group=-20)

    # banned users
    dispatcher.add_handler(TypeHandler(Update, callback_all), group=-10)

    # automated responses
    dispatcher.add_handler(MessageHandler(Filters.text, command_answer), group=30)

    # commands
    dispatcher.add_handler(CommandHandler('fortune', command_fortune), group=40)
    dispatcher.add_handler(CommandHandler('tip', command_tip), group=40)
    dispatcher.add_handler(CommandHandler('oiga', command_oiga), group=40)
    dispatcher.add_handler(CommandHandler('stats', command_stats), group=40)
    dispatcher.add_handler(CommandHandler('normalize', command_normalize), group=40)
    dispatcher.add_handler(CommandHandler('restart', command_restart), group=40)
    dispatcher.add_handler(CommandHandler('debug', command_debug), group=40)
    dispatcher.add_handler(CommandHandler('info', command_info), group=40)
    dispatcher.add_handler(CommandHandler('text', command_text), group=40)
    dispatcher.add_handler(CommandHandler('thread', command_thread, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('translate', command_translate, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('scramble', command_scramble, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('distort', command_distort, run_async=True), group=40)
    # CommandHandlers don't work on captions, so all photos with a caption are sent to a
    # fun that will check for the command and then run command_distort if necessary
    dispatcher.add_handler(MessageHandler(Filters.caption & Filters.chat_type.group,
                                          command_distort_caption, run_async=True), group=41)

    # responses in private
    dispatcher.add_handler(MessageHandler((Filters.text | Filters.poll) & ~Filters.command & Filters.chat_type.private,
                                          command_scramble, run_async=True), group=40)
    dispatcher.add_handler(MessageHandler((Filters.photo | Filters.animation | Filters.video) & ~Filters.command & Filters.chat_type.private,
                                          command_distort, run_async=True), group=40)
    dispatcher.add_handler(MessageHandler(Filters.chat_type.private, command_catchall, run_async=True), group=40)

    dispatcher.job_queue.run_repeating(cron_delete, interval=20)

    dispatcher.job_queue.run_repeating(actions.cron, interval=4)

    first_cron = datetime.datetime.now().astimezone()
    if first_cron.hour % 2 == 0:
        first_cron += datetime.timedelta(hours=2)
    else:
        first_cron += datetime.timedelta(hours=1)
    first_cron = first_cron.replace(minute=0, second=0, microsecond=0)
    print('first cron scheduled for %s' % first_cron.isoformat())
    dispatcher.job_queue.run_repeating(cron_4chan, first=first_cron,
                                       interval=60 * 60 * 2)

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
