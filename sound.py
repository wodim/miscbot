from glob import glob
import os
import subprocess
from textwrap import wrap

from telegram import ChatAction, Update
from telegram.constants import MAX_MESSAGE_LENGTH
from telegram.error import NetworkError
from telegram.ext import CallbackContext

from utils import get_random_string


def command_sound_list(update: Update, _: CallbackContext) -> str:
    """lists all the sound folders"""
    update.message.reply_text(' '.join(sorted(['/' + folder.replace('sound/', '').lower()
                                               for folder in glob('sound/*')])))


FFMPEG_CMD_CONCATENATE = ("ffmpeg {inputs} -filter_complex '{streams}concat=n={input_count}:v=0:a=1[out]' "
                          "-map '[out]' -map_metadata -1 -vbr on -c:a libopus '{output}'")
FFMPEG_INPUT_FORMAT = "-i '{input_}' "
FFMPEG_STREAM_FORMAT = '[{i}:0]'
def command_sound(update: Update, context: CallbackContext) -> str:
    """merges one or several audios into a single voice message"""
    command = update.message.text.split(' ')[0][1:].replace('@' + context.bot_data['me'].username, '')
    # this safeguard is not really necessary, but better safe than sorry
    if not all(x.isalnum() for x in command):
        return
    folder = f'sound/{command}/'.lower()

    # print help message if no params
    if not context.args:
        words = ' '.join(sorted([x.replace(folder, '').replace('.wav', '')
                                for x in glob(f'{folder}*.wav')]))
        messages = wrap(words, MAX_MESSAGE_LENGTH)
        for message in messages:
            update.message.reply_text(message)
        return

    input_files = []
    for file in context.args:
        fullpath = f'{folder}{file}.wav'
        if not os.path.isfile(fullpath):
            update.message.reply_text(f'Word not available: {file}')
            return
        input_files.append(fullpath)

    # figure out the absurdly complicated command line
    inputs = ''
    streams = ''
    output = get_random_string(12) + '.ogg'
    for i, file in enumerate(input_files):
        inputs += FFMPEG_INPUT_FORMAT.format(input_=file)
        streams += FFMPEG_STREAM_FORMAT.format(i=i)
    command = FFMPEG_CMD_CONCATENATE.format(inputs=inputs, streams=streams,
                                            input_count=len(input_files),
                                            output=output)

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.RECORD_VOICE)

    if subprocess.call(command, shell=True) != 0:
        update.message.reply_text('Error generating audio.')
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.RECORD_VOICE)
        return

    try:
        update.message.reply_voice(voice=open(output, 'rb'), quote=False)
    except NetworkError:
        update.message.reply_text('The resulting file is too big.')

    context.bot_data['actions'].remove(update.message.chat_id, ChatAction.RECORD_VOICE)

    os.remove(output)
