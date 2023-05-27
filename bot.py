import datetime
from glob import glob
import html
from inspect import getdoc
import os
import pprint
import random
import signal
import socket

import requests
from telegram import Bot, Update
from telegram.constants import MAX_MESSAGE_LENGTH, PARSEMODE_HTML
from telegram.ext import (CallbackContext, CommandHandler, DispatcherHandlerStop,
                          Filters, MessageHandler, TypeHandler, Updater)
from telegram.utils.request import Request

from _4chan import cron_4chan, command_thread
from calc import command_calc
from craiyon import command_craiyon, command_dalle
from distort import (command_photo, command_distort, command_distort_caption,
                     command_invert, command_voice, command_wtf)
from huggingface import HuggingFaceFormat, huggingface
from message_history import MessageHistory
from queues import Actions, Edits
from relay import (command_relay_chat_photo, command_relay_text, command_relay_photo,
                   cron_delete)
from sound import command_sound, command_sound_list
from soyjak import command_soyjak, cron_soyjak
from text import command_fortune, command_imp, command_haiku, command_tip, command_oiga
from translate import command_translate
from twitter import command_twitter, cron_twitter
from utils import (_config, _config_list, clean_up, ellipsis,
                   get_command_args, get_relays, logger, is_admin,
                   send_admin_message)


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
        try:
            with open('restart', 'wb') as fp:
                fp.write(b'%d' % update.message.chat.id)
        except Exception as exc:
            update.message.reply_text(f"Couldn't save restart state file: {str(exc)}")
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
    """flushes the pending action list"""
    if is_admin(update.message.from_user.id):
        actions.flush()
        update.message.reply_text('Done.')
    else:
        update.message.reply_animation(_config('error_animation'))


def command_unhandled(update: Update, _: CallbackContext) -> None:
    """handles unknown commands"""
    update.message.reply_animation(_config('error_animation'))


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
    if update.message.from_user.id in _config_list('banned_users', int):
        raise DispatcherHandlerStop()
    if (not is_admin(update.message.from_user.id) and
            update.message.chat.type in ('group', 'supergroup') and
            update.message.chat.id in _config_list('muted_groups', int)):
        raise DispatcherHandlerStop()


def command_trigger(update: Update, _: CallbackContext) -> None:
    """replies to some text triggers and stops handling"""
    if not update.message or not update.message.text:
        return
    if update.message.chat.id in _config_list('muted_groups', int):
        return
    with open('triggers.txt', 'rt', encoding='utf8') as fp:
        triggers = [x.split('\t') for x in fp.readlines()]
    for trigger, answer in triggers:
        if update.message.text.lower() == trigger.lower():
            update.message.reply_text(answer, quote=False)
            raise DispatcherHandlerStop()


def command_send(update: Update, context: CallbackContext) -> None:
    """returns a media object by id"""
    if len(context.args) != 2:
        update.message.reply_text('Usage: /send <photo animation video audio voice sticker contact...> <id>')
        return
    try:
        fun = getattr(update.message, f'reply_{context.args[0]}')
    except AttributeError:
        update.message.reply_text('Invalid kind of media object.')
        return
    try:
        fun(context.args[1])
    except Exception as exc:
        update.message.reply_text(f'Error: {exc}')


def command_clear(update: Update, _: CallbackContext) -> None:
    """clears all temporary files"""
    if not is_admin(update.message.from_user.id):
        update.message.reply_animation(_config('error_animation'))
        return
    if files := (glob('*.jpg') + glob('*.webm') + glob('*.tgs') + glob('*.webp') +
                 glob('translate_tmp_*.txt') + glob('*.mp4') + glob('*.ogg') + glob('*.png') +
                 glob('downloader_*.tmp')):
        for file in files:
            os.remove(file)
        all_files = ' '.join(files)
        update.message.reply_text(ellipsis(f'Removed {len(files)} file(s): {all_files}', MAX_MESSAGE_LENGTH))
    else:
        update.message.reply_text('There were no temporary files to remove.')


def command_load(update: Update, _: CallbackContext) -> None:
    """returns the current load average"""
    update.message.reply_text(f'Load average: {str(os.getloadavg())[1:-1]}')


def command_config(update: Update, context: CallbackContext) -> None:
    """replies with the entire config file, partially redacted if called in
    a public chat or by someone who's not an admin"""
    def format_config_key(k: str, v: str) -> str:
        is_admin_chat = update.message.chat.id in _config_list('admins', int)
        is_secret = lambda k: k in (
            'token chat_relays chat_relay_delete_channel banned_users '
            '4chan_cron_chat_id muted_groups '
            'ipgeolocation_io_api_key soyjak_cron_chat_id twitter_feeds '
            'twitter_consumer_key twitter_consumer_secret '
            'twitter_access_token twitter_access_token_secret'
        ).split(' ')
        should_show = lambda k: not is_secret(k) or (is_secret(k) and is_admin_chat)
        return '<strong>%s = </strong>%s' % (
            html.escape(k), html.escape(v) if should_show(k) else '<em>(hidden)</em>')

    if context.args:
        k = context.args[0].lower()
        if v := _config(k):
            update.message.reply_text(format_config_key(k, v),
                                      quote=False, parse_mode=PARSEMODE_HTML,
                                      disable_web_page_preview=True)
        else:
            update.message.reply_text('No such key.')
    else:
        update.message.reply_text('\n'.join([
                format_config_key(k, v) for k, v in sorted(_config())
            ]), quote=False, parse_mode=PARSEMODE_HTML, disable_web_page_preview=True)


def command_leave(update: Update, context: CallbackContext) -> None:
    """leaves a chat"""
    if is_admin(update.message.from_user.id):
        if len(context.args) != 1:
            help_text = 'Usage: /leave <chat id>'
            if update.message.chat.type != 'private':
                help_text += f'\n\nIf you want me to leave this chat, use:\n/leave {update.message.chat.id}'
            update.message.reply_text(help_text)
            return
        try:
            chat_id = int(context.args[0])
        except ValueError:
            update.message.reply_text('Chat ID must be a number.')
            return
        try:
            context.bot.leave_chat(chat_id)
        except Exception as exc:
            update.message.reply_text(f'Error leaving chat: {exc}')
    else:
        update.message.reply_animation(_config('error_animation'))


def command_strip(update: Update, context: CallbackContext) -> None:
    """forwards back the quoted message without a "forwarded from" header
    or a caption if applicable"""
    if update.message.reply_to_message and update.message.reply_to_message.effective_attachment:
        # this is tricky
        attachment = update.message.reply_to_message.effective_attachment
        if isinstance(attachment, list):
            attachment = attachment[-1]
        base_name = 'Photo' if attachment.__class__.__name__ == 'PhotoSize' else attachment.__class__.__name__
        try:
            fun = getattr(context.bot, f'send{base_name}')
        except AttributeError:
            update.message.reply_text(f"I can't handle this type of attachment: {base_name}")
            return
        try:
            fun(update.message.chat.id, attachment)
        except Exception as exc:
            update.message.reply_text(f'Something happened: {exc}')
    elif update.message.reply_to_message:
        update.message.reply_text("This message doesn't have an attachment.")
    else:
        update.message.reply_text('Quote a message to have its contents dumped here.')


def command_ip(update: Update, _: CallbackContext) -> None:
    """prints geolocation information"""
    if text := get_command_args(update):
        def uniq(keys):
            things = {r.get(x): None for x in keys if r.get(x)}
            return  ', '.join(things.keys()) if things != {None: None} else None

        api_key = _config('ipgeolocation_io_api_key')
        try:
            r = requests.get(f'https://api.ipgeolocation.io/ipgeo?ip={text}&apiKey={api_key}').json()
        except:
            return update.message.reply_text('An error occurred when sending the API request.')
        if r.get('message'):
            if 'IP to geolocation lookup for domain' in r['message']:
                # it's a hostname so do a second pass resolving first
                try:
                    text = socket.gethostbyname(text)
                    r = requests.get(f'https://api.ipgeolocation.io/ipgeo?ip={text}&apiKey={api_key}').json()
                except:
                    logger.exception("Couldn't resolve %s", text)
                    return update.message.reply_text(f"Couldn't resolve {text}")
            else:
                logger.info('Error returned: %s', r['message'])
                return update.message.reply_text(f'An error occurred: {r["message"]}')
        message = f'<b>IP geolocation for {text}:</b>\n'
        if location := uniq(['district', 'city', 'state_prov', 'country_name']):
            message += f'<b>Location:</b> {location} <a href="https://www.google.com/maps/search/{location}/">[map]</a>\n'
        if organization := uniq(['isp', 'organization']):
            message += f'<b>ISP:</b> {organization}\n'
        update.message.reply_text(message, parse_mode=PARSEMODE_HTML,
                                  disable_web_page_preview=True)
    else:
        update.message.reply_text('Specify an IP address or host name.')


def command_help(update: Update, _: CallbackContext) -> None:
    """returns a list of all available commands"""
    commands = []
    for _, handlers in dispatcher.handlers.items():
        for handler in handlers:
            if isinstance(handler, CommandHandler):
                doc = getdoc(handler.callback).replace('\n', ' ')
                slashes = ' '.join(['/' + x for x in handler.command])
                commands.append(f'<strong>{slashes}</strong> - {doc}')
    message = ('\n'.join(commands) +
               '\n\nUse the <b>/contact</b> command to contact the admin(s) of the bot.')
    update.message.reply_text(message, parse_mode=PARSEMODE_HTML)


CONTACT_HELP = """You can use this command to contact the admin(s) of this bot.\n
Usage: /contact <your message>\n
Your message, along with your username, will be delivered."""
def command_contact(update: Update, _: CallbackContext) -> None:
    """sends a message to all admins"""
    if message := get_command_args(update, use_quote=False):
        from_ = update.message.from_user.first_name
        if update.message.from_user.last_name:
            from_ += f' {update.message.from_user.last_name}'
        if update.message.from_user.username:
            from_ += f' @{update.message.from_user.username}'
        send_admin_message(bot, f'Message from {from_}:\n\n{message[:4000]}')
        update.message.reply_text('Your message has been delivered.')
    else:
        update.message.reply_text(CONTACT_HELP)


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


if __name__ == '__main__':
    logger.info('Hello!!!')
    # connection pool size is workers + updater + dispatcher + job queue + main thread
    num_threads = int(_config('num_threads'))
    request = Request(con_pool_size=num_threads + 4)
    bot = Bot(_config('token'), request=request)
    updater = Updater(bot=bot, workers=num_threads)
    logger.info("Connected! I'm %s, running with %d threads.", bot.name, num_threads)

    message_history = MessageHistory()
    actions_cron_interval = int(_config('actions_cron_interval'))
    actions = Actions(bot, updater.dispatcher.job_queue, actions_cron_interval)
    edits_cron_interval = int(_config('edits_cron_interval'))
    edits = Edits(bot, updater.dispatcher.job_queue, edits_cron_interval)

    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    dispatcher.bot_data.update({
        'message_history': message_history,
        'actions': actions,
        'edits': edits,
        'me': bot.get_me(),
        'last_tweet_ids': {},
    })

    logger.info('Adding handlers...')

    # relays
    sources = get_relays().keys()
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.text & ~Filters.command & Filters.update.message,
                                          command_relay_text, run_async=True), group=-20)
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & (Filters.photo | Filters.sticker) & Filters.update.message,
                                          command_relay_photo, run_async=True), group=-20)
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & (Filters.status_update.new_chat_photo |
                                                                   Filters.status_update.delete_chat_photo),
                                          command_relay_chat_photo, run_async=True), group=-20)

    # banned users and muted groups
    dispatcher.add_handler(TypeHandler(Update, callback_all), group=-10)

    # automated responses
    dispatcher.add_handler(MessageHandler(Filters.chat(sources) & Filters.text, command_trigger), group=30)

    # commands
    dispatcher.add_handler(CommandHandler('help', command_help), group=40)
    dispatcher.add_handler(CommandHandler('start', command_fortune), group=40)
    dispatcher.add_handler(CommandHandler('fortune', command_fortune), group=40)
    dispatcher.add_handler(CommandHandler('tip', command_tip), group=40)
    dispatcher.add_handler(CommandHandler('oiga', command_oiga), group=40)
    # this one needs to be async because we call an external program and we wait for it to die.
    dispatcher.add_handler(CommandHandler('calc', command_calc, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('normalize', command_normalize), group=40)
    dispatcher.add_handler(CommandHandler('restart', command_restart), group=40)
    dispatcher.add_handler(CommandHandler('debug', command_debug), group=40)
    dispatcher.add_handler(CommandHandler('flush', command_flush), group=40)
    dispatcher.add_handler(CommandHandler('info', command_info), group=40)
    dispatcher.add_handler(CommandHandler('text', command_text), group=40)
    dispatcher.add_handler(CommandHandler('send', command_send), group=40)
    dispatcher.add_handler(CommandHandler('sound', command_sound_list), group=40)
    dispatcher.add_handler(CommandHandler('load', command_load), group=40)
    dispatcher.add_handler(CommandHandler('config', command_config), group=40)
    dispatcher.add_handler(CommandHandler('haiku', command_haiku), group=40)
    dispatcher.add_handler(CommandHandler('imp', command_imp), group=40)
    dispatcher.add_handler(CommandHandler('leave', command_leave), group=40)
    dispatcher.add_handler(CommandHandler('strip', command_strip), group=40)
    dispatcher.add_handler(CommandHandler('contact', command_contact), group=40)
    dispatcher.add_handler(CommandHandler('twitter', command_twitter), group=40)
    dispatcher.add_handler(CommandHandler('thread', command_thread, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('clear', command_clear, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('translate', command_translate, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler(['distort', 'scramble'], command_distort, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('voice', command_voice, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('invert', command_invert, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('photo', command_photo, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('craiyon', command_craiyon, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('dalle', command_dalle, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('sd', command_sd, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('sd1', command_sd1, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('ai', command_craiyon, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('ai', command_sd, run_async=True), group=41)
    dispatcher.add_handler(CommandHandler('gfpgan', command_gfpgan, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('ip', command_ip, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('soyjak', command_soyjak, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('caption', command_caption, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('anime', command_anime, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('wtf', command_wtf, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler('clip', command_clip, run_async=True), group=40)
    dispatcher.add_handler(MessageHandler(Filters.photo & ~Filters.command & Filters.chat_type.groups & Filters.chat(_config_list('auto_captions', int)),
                                          command_caption, run_async=True), group=40)
    dispatcher.add_handler(CommandHandler([x.replace('sound/', '') for x in glob('sound/*')], command_sound, run_async=True), group=40)
    # CommandHandlers don't work on captions, so all photos with a caption are sent to a
    # fun that will check for the command and then run command_distort if necessary
    dispatcher.add_handler(MessageHandler(Filters.caption & Filters.chat_type.group,
                                          command_distort_caption, run_async=True), group=41)

    # responses in private
    dispatcher.add_handler(MessageHandler(~Filters.command & Filters.chat_type.private, command_distort, run_async=True), group=40)
    dispatcher.add_handler(MessageHandler(Filters.chat_type.private, command_unhandled, run_async=True), group=40)

    logger.info('Adding jobs to the queue...')

    dispatcher.job_queue.run_repeating(cron_delete, interval=20)

    dispatcher.job_queue.run_repeating(cron_twitter, interval=10, first=1)

    if actions_cron_interval > 0:
        dispatcher.job_queue.run_repeating(actions.cron, interval=actions_cron_interval, name='actions').enabled = False
    if edits_cron_interval > 0:
        dispatcher.job_queue.run_repeating(edits.cron, interval=edits_cron_interval, name='edits').enabled = False

    first_cron = datetime.datetime.now().astimezone() + datetime.timedelta(hours=1)
    first_cron = first_cron.replace(minute=0, second=0, microsecond=0)
    dispatcher.job_queue.run_repeating(cron_4chan, first=first_cron, interval=60 * 60)
    dispatcher.job_queue.run_repeating(cron_soyjak, first=first_cron, interval=60 * 60)

    logger.info('Setting commands...')

    bot.set_my_commands([
        ('fortune',      '🥠'),
        ('imp',          '😈'),
        ('translate',    '㊙️'),
        ('distort',      '🔨'),
        ('thread',       '🍀'),
        ('calc',         '🧮'),
        ('craiyon',      '🎨'),
        ('sd',           '🖼️'),
        ('gfpgan',       '📈'),
        ('soyjak',       '🥛'),
        ('caption',      '🔤'),
        ('anime',        '🌸'),
        ('wtf',          '🤔'),
    ])

    logger.info('Booting poller...')

    # Start the Bot
    updater.start_polling()

    try:
        with open('restart', 'rb') as fp:
            bot.send_animation(int(fp.read()), _config('restart_animation'))
        os.remove('restart')
    except FileNotFoundError:
        send_admin_message(bot, "I'm back.")

    logger.info("We're on!")

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()
