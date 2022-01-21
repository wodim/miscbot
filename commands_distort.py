from glob import glob
import os
import re
import subprocess
import threading

from telegram import ChatAction, Update
from telegram.ext import CallbackContext
from wand.image import Image

from utils import _config, get_random_string, logger, remove_command


DISTORT_FORMAT = 'jpg'
MAX_SCORE = 800 * 600 * 1000


distort_semaphore = threading.Semaphore(int(_config('max_concurrent_distorts')))
def sub_distort(source: str, output: str = '', scale: float = -1, dimension: str = '') -> str:
    """distorts an image. returns the file name of the distorted image."""
    if not 0 < scale < 100:
        scale = 60
    if dimension not in ('h', 'w', '*'):
        dimension = '*'
    if not output:
        output = 'distorted_' + source

    with distort_semaphore:
        img = Image(filename=source)
        w, h = img.width, img.height
        if w % 2 != 0:
            w += 1
        if h % 2 != 0:
            h += 1
        new_w = int(w * (1 - (scale / 100))) if dimension in ('*', 'w') else w
        new_h = int(w * (1 - (scale / 100))) if dimension in ('*', 'h') else h
        img.liquid_rescale(new_w, new_h)
        img.resize(w, h)
        img.compression_quality = 100
        img.save(filename=output)
        img.destroy()
        img.close()

    return output


FFMPEG_CMD_GET_INFO = "ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets,avg_frame_rate,width,height -of csv=p=0 '{source}'"
FFMPEG_CMD_HAS_AUDIO = "ffprobe -v error -select_streams a:0 -show_entries stream=index -of csv=p=0 '{source}'"
FFMPEG_CMD_EXTRACT = "ffmpeg -hide_banner -i '{source}' -map 0:v:0 -q:v 2 '{prefix}-%06d." + DISTORT_FORMAT + "'"
FFMPEG_CMD_COMPOSE = "ffmpeg -framerate {fps} -i '{prefix}-distort-%06d." + DISTORT_FORMAT + "' -c:v libx264 -pix_fmt yuv420p '{prefix}.mp4'"
FFMPEG_CMD_COMPOSE_WITH_AUDIO = "ffmpeg -framerate {fps} -i '{prefix}-distort-%06d." + DISTORT_FORMAT + "' -i '{original}' -map 0:v -map 1:a -c:v libx264 -pix_fmt yuv420p '{prefix}.mp4'"
MIN_DISTORT = 10
MAX_DISTORT = 80
PHOTO_TO_GIF_FRAMES = 100
RX_NUMBER = re.compile(r'\-\d{6}')
def sub_distort_animation(filename: str) -> str:
    def remap(x, in_min, in_max, out_min, out_max):
        return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min
    def distorted_name(source, i):
        source = RX_NUMBER.sub('', source)
        return '%s-distort-%06d%s' % (source[:len(source) - 4], i, source[len(source) - 4:])

    if filename.endswith('.mp4'):
        output = subprocess.check_output(FFMPEG_CMD_GET_INFO.format(source=filename), shell=True).decode('utf8').strip()
        try:
            parts = output.split(',')
            width = int(parts[0])
            height = int(parts[1])
            fps = parts[2]
            frame_count = int(parts[3])
        except (ValueError, IndexError):
            raise ValueError("This doesn't look like a valid video.")

        score = frame_count * width * height
        if score > MAX_SCORE:
            raise ValueError(f'Video is too long or large ({score}; maximum is {MAX_SCORE}).')

        output = subprocess.check_output(FFMPEG_CMD_HAS_AUDIO.format(source=filename), shell=True)
        has_audio = len(output) > 1

        prefix = get_random_string(32)

        if subprocess.call(FFMPEG_CMD_EXTRACT.format(source=filename, prefix=prefix), shell=True) != 0:
            raise ValueError('Error extracting frames.')

        frames = sorted(glob(f'{prefix}*.{DISTORT_FORMAT}'))
    else:
        frames = [filename] * PHOTO_TO_GIF_FRAMES
        fps = 30
        has_audio = False
        prefix = filename[:-4]

    distorted = []
    for i, frame in enumerate(frames):
        distorted.append(sub_distort(frame, distorted_name(frame, i), remap(i, 0, len(frames) - 1, MIN_DISTORT, MAX_DISTORT)))

    if has_audio:
        if subprocess.call(FFMPEG_CMD_COMPOSE_WITH_AUDIO.format(fps=fps, prefix=prefix, original=filename), shell=True) != 0:
            raise ValueError('Error generating video.')
    else:
        if subprocess.call(FFMPEG_CMD_COMPOSE.format(fps=fps, prefix=prefix), shell=True) != 0:
            raise ValueError('Error generating video.')

    if filename.endswith('.mp4'):
        for frame in frames:
            os.remove(frame)
    for file in distorted:
        os.remove(file)

    return prefix + '.mp4'


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
    elif update.message.animation:
        filename = context.bot.get_file(update.message.animation.file_id).\
            download(custom_path=get_random_string(12) + '.mp4')
    elif update.message.reply_to_message and update.message.reply_to_message.animation:
        filename = context.bot.get_file(update.message.reply_to_message.animation.file_id).\
            download(custom_path=get_random_string(12) + '.mp4')
    elif update.message.video:
        filename = context.bot.get_file(update.message.video.file_id).\
            download(custom_path=get_random_string(12) + '.mp4')
    elif update.message.reply_to_message and update.message.reply_to_message.video:
        filename = context.bot.get_file(update.message.reply_to_message.video.file_id).\
            download(custom_path=get_random_string(12) + '.mp4')
    else:
        update.message.reply_text('Nothing to distort. Upload or quote a photo or GIF.')
        return

    if filename.endswith('.jpg'):
        command_distort_photo(update, context, filename, text)
    else:
        command_distort_animation(update, context, filename)


def command_distort_animation(update: Update, context: CallbackContext, filename: str) -> None:
    context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_VIDEO)

    try:
        animation = sub_distort_animation(filename)
    except Exception as exc:
        logger.exception('Error distorting')
        update.message.reply_text('Error distorting: ' + str(exc))
        return
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_VIDEO)

    update.message.reply_animation(animation=open(animation, 'rb'))

    os.remove(filename)
    os.remove(animation)


def command_distort_photo(update: Update, context: CallbackContext, filename: str, text: str) -> None:
    def parse_distort_params(params):
        dimension = '*'
        scale = -1
        for param in params:
            try:
                scale = int(param)
            except:
                pass
            if param in ('h', 'w'):
                dimension = param
        return scale, dimension

    params = remove_command(text).split(' ')

    try:
        if 'gif' in params:
            context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_VIDEO)
            distorted_filename = sub_distort_animation(filename)
        else:
            context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_PHOTO)
            distorted_filename = sub_distort(filename, None, *parse_distort_params(params))
    except Exception as exc:
        logger.exception('Error distorting')
        update.message.reply_text('Error distorting: %s' % exc)
        # the original is kept for troubleshooting
        return
    finally:
        if 'gif' in params:
            context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_VIDEO)
        else:
            context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_PHOTO)

    fun = update.message.reply_animation if 'gif' in params else update.message.reply_photo
    with open(distorted_filename, 'rb') as fp:
        fun(fp)

    os.remove(filename)
    os.remove(distorted_filename)


RX_COMMAND_CHECK = re.compile(r'^/distort(@aryan_bot)?(\s|$)', re.IGNORECASE)
def command_distort_caption(update: Update, context: CallbackContext) -> None:
    """check if a photo with caption has a distort command. if so, distorts it.
    else, it does nothing."""
    if RX_COMMAND_CHECK.match(update.message.caption):
        command_distort(update, context)
