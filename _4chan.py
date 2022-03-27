import datetime
import os
import random
import re
import shutil
import subprocess

import bs4
import requests
from telegram import ChatAction, Update
from telegram.constants import PARSEMODE_MARKDOWN_V2
from telegram.ext import CallbackContext
from telegram.utils.helpers import escape_markdown

from utils import _config, _config_list, logger


class _4chan:
    CATALOG_URL = 'https://boards.4chan.org/%s/catalog'
    THREAD_URL = 'https://boards.4chan.org/%s/thread/%d'

    def __init__(self):
        self.rx_thread_ids = re.compile(r'[{\,]"(\d+)\":{')

    @staticmethod
    def _download_file(url, name):
        if os.path.exists(name):
            return name

        if url.startswith('//'):
            url = 'https:' + url
        logger.info('downloading from %s to %s', url, name)
        with requests.get(url, stream=True) as r:
            with open(name, 'wb') as f:
                shutil.copyfileobj(r.raw, f)
        logger.info('done downloading from %s', url)

        return name

    @staticmethod
    def _soup_to_text(soup):
        """turn a soup element into plain text"""
        text = ''

        if not soup:
            return text

        for element in soup.contents:
            if isinstance(element, bs4.element.Tag) and element.name == 'br':
                text += '\n'
            elif element.string:
                text += element.string
            elif element.text:
                text += element.text

        return text

    def _request_thread(self, board, thread):
        """makes an http request to obtain a thread and parses it"""
        url = self.THREAD_URL % (board, thread,)
        logger.info('requesting %s ...', url)

        r = requests.get(url)
        if r.status_code != requests.codes.ok:
            raise RuntimeError("couldn't request a thread: %d" % r.status_code)

        soup = bs4.BeautifulSoup(r.text, features='html.parser')
        # find the op message container
        soup_op = soup.find('div', class_='opContainer')
        # inside, the metadata
        soup_info = soup_op.find('div', class_='postInfo')
        # and inside the metadata, the subject if any
        subject = soup_info.find('span', class_='subject').string
        if subject:
            subject = str(subject)
        # file: get info and download and store it
        soup_file = soup_op.find('div', class_='file')
        try:
            image_info = ' '.join(soup_file.find('div', class_='fileText').strings)
            image_url = soup_file.find('a', class_='fileThumb')['href']
            image_file = self._download_file(image_url, 'image_%s_%d.%s' %
                                             (board, thread, image_url.split('.')[-1]))
        except AttributeError:
            image_info = '(file deleted)'
            image_url, image_file = None, None
        # and finally the text
        soup_message = soup_op.find('blockquote', class_='postMessage')
        text = self._soup_to_text(soup_message)

        return {'url': self.THREAD_URL % (board, thread,),
                'subject': subject,
                'image_url': image_url,
                'image_file': image_file,
                'image_info': image_info,
                'text': text}

    def thread_info(self, board, thread):
        """returns info about a thread"""
        logger.info('retrieving thread /%s/%s', board, thread)
        thread_content = self._request_thread(board, thread)
        logger.info('done retrieving thread /%s/%s', board, thread)
        return thread_content

    def threads_in_board(self, board):
        """returns a list of all threads in a board"""
        logger.info('retrieving board /%s/', board)
        r = requests.get(self.CATALOG_URL % board)
        if r.status_code != requests.codes.ok:
            raise RuntimeError("couldn't request the board catalog: %d" % r.status_code)
        threads_ids = [int(x) for x in self.rx_thread_ids.findall(r.text)]
        logger.info('done retrieving /%s/', board)
        return threads_ids


def cron_4chan(context: CallbackContext) -> None:
    hour = datetime.datetime.now().astimezone().hour
    if hour % 2 == 1 or 2 < hour < 10:
        return
    post_thread(int(_config('4chan_cron_chat_id')), context)


def command_thread(update: Update, context: CallbackContext) -> None:
    try:
        post_thread(update.message.chat_id, context, context.args)
    except Exception as exc:
        update.message.reply_text(repr(exc), quote=False)
        raise


FFMPEG_CMD = "ffmpeg -hide_banner -i '{source}' -vf 'pad=ceil(iw/2)*2:ceil(ih/2)*2' -preset veryfast '{dest}'"
def _webm_convert(file: str) -> str:
    """converts a webm to a mp4 file"""
    new_file = file + '.mp4'
    if os.path.exists(new_file):
        return new_file

    logger.info('converting %s to %s', file, new_file)
    subprocess.call(FFMPEG_CMD.format(source=file, dest=new_file), shell=True)
    if not os.path.exists(new_file) or os.path.getsize(new_file) == 0:
        raise RuntimeError("for some reason, %s wasn't created" % new_file)

    os.remove(file)

    return new_file


_4c = _4chan()
RX_GREENTEXT = re.compile(r'^(\\>.*)$', re.MULTILINE)
def post_thread(chat_id: int, context: CallbackContext, args: list = None) -> None:
    def _e(text):
        """escapes text with markdown v2 syntax"""
        return escape_markdown(text, 2)

    context.bot_data['actions'].append(chat_id, ChatAction.TYPING)

    board = args[0] if args else random.choice(_config_list('4chan_boards'))
    threads = _4c.threads_in_board(board)
    thread = _4c.thread_info(board, random.choice(threads))

    text = ''

    # text = '_%s_\n\n' % _e(thread['image_info'])

    thread_text = thread['text']
    if len(thread_text) > 3000:
        thread_text = thread_text + '…'
    thread_text = RX_GREENTEXT.sub(r'_\1_', _e(thread_text))
    if thread['subject'] and thread_text:
        text += '*%s*\n%s' % (_e(thread['subject']), thread_text,)
    elif thread['subject']:
        text = _e(thread['subject'])
    else:
        text = thread_text

    text += '\n\n' + _e(thread['url'])

    if thread['image_url']:
        if thread['image_url'].endswith('.webm'):
            thread['image_file'] = _webm_convert(thread['image_file'])
        if thread['image_url'].endswith('.gif') or thread['image_url'].endswith('.webm'):
            fun = context.bot.send_video
        else:
            fun = context.bot.send_photo
        with open(thread['image_file'], 'rb') as fp:
            fun(chat_id, fp)

    os.remove(thread['image_file'])

    context.bot.send_message(chat_id, '%s' % text,
                             parse_mode=PARSEMODE_MARKDOWN_V2,
                             disable_web_page_preview=True)

    context.bot_data['actions'].remove(chat_id, ChatAction.TYPING)
