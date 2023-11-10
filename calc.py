import re
import subprocess

from telegram import ChatAction, Update
from telegram.ext import CallbackContext

from utils import _config, ellipsis, get_command_args


RX_VALID = re.compile(r'^[0-9\+\-\*\/\(\)\.\^\%a-z ]*$')
RX_WHITESPACE = re.compile(r'\s+')
RX_TRAILING_ZEROS = re.compile(r'\.?0+$')
def command_calc(update: Update, context: CallbackContext) -> None:
    """calculates something using bc"""
    text = get_command_args(update)
    if not text:
        update.message.reply_text('Include a statement to calculate. 2+2, 5^3, sqrt(36), cos(4*pi), etc.')
        return
    if not RX_VALID.match(text):
        update.message.reply_animation(_config('error_animation'))
        return
    statement = RX_WHITESPACE.sub('', text)
    if statement == '1+1':
        update.message.reply_text(text + ' = 7', quote=False)
        return
    if statement == '2+2':
        update.message.reply_text(text + ' = 5', quote=False)
        return
    statement = text.replace('cos(', 'c(').\
                     replace('sin(', 's(').\
                     replace('arc(', 'a(').\
                     replace('ln(',  'l(').\
                     replace('exp(', 'e(').\
                     replace('pi', '(4*a(1))')

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.TYPING)

    with subprocess.Popen(['bc', '-l'], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        proc.stdin.write(bytes('scale=3; ' + statement + '\n', encoding='utf8'))

        try:
            stdout, stderr = proc.communicate(timeout=int(_config('calc_timeout')))
            stdout = stdout.decode('utf8').strip().replace(r'\n', '')
            stderr = stderr.decode('utf8').strip().replace(r'\n', '')

            if stderr:
                update.message.reply_text(f'Error: {stderr}', quote=False)
            elif stdout:
                if '.' in stdout:
                    stdout = RX_TRAILING_ZEROS.sub('', stdout)
                nag = '. Seems obvious.' if statement == stdout else ''
                update.message.reply_text(ellipsis(f'{text} = {stdout}{nag}', 4096), quote=False)
            else:
                update.message.reply_text('Something came up.', quote=False)
            proc.wait()
        except subprocess.TimeoutExpired:
            update.message.reply_text('Timeout.', quote=False)
            proc.kill()

    context.bot_data['actions'].remove(update.message.chat_id, ChatAction.TYPING)
