import re
import subprocess

from telegram import Update
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
        context.bot.send_message(update.message.chat.id, text + ' = 7')
        return
    if statement == '2+2':
        context.bot.send_message(update.message.chat.id, text + ' = 5')
        return
    statement = text.replace('cos(', 'c(').\
                     replace('sin(', 's(').\
                     replace('arc(', 'a(').\
                     replace('ln(',  'l(').\
                     replace('exp(', 'e(').\
                     replace('pi', '(4*a(1))')
    with subprocess.Popen(['bc', '-l'], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        proc.stdin.write(bytes(statement + '\n', encoding='utf8'))

        try:
            stdout, stderr = proc.communicate(timeout=5)
            stdout = stdout.decode('utf8').strip().replace('\\\n', '')
            stderr = stderr.decode('utf8').strip().replace('\\\n', '')
        except subprocess.TimeoutExpired:
            context.bot.send_message(update.message.chat.id, 'Timeout.')
            proc.kill()

        if stderr:
            context.bot.send_message(update.message.chat.id, 'Error: ' + stderr)
        elif stdout:
            if '.' in stdout:
                stdout = RX_TRAILING_ZEROS.sub('', stdout)
            nag = '. Seems obvious.' if statement == stdout else ''
            context.bot.send_message(update.message.chat.id, ellipsis('%s = %s%s' % (text, stdout, nag), 4096))
        else:
            context.bot.send_message(update.message.chat.id, 'Something came up.')
        proc.wait()
