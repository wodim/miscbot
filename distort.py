from glob import glob
import gzip
import json
import os
import random
import re
from shutil import copy2
import subprocess
import threading

from telegram import ChatAction, Update
from telegram.constants import MAX_MESSAGE_LENGTH
from telegram.error import BadRequest
from telegram.ext import CallbackContext
from wand.image import Image

from attachments import AttachmentType, download_attachment
from translate import sub_scramble
from utils import _config, clamp, ellipsis, get_command_args, get_random_string, logger, remove_command


DISTORT_FORMAT = _config('distort_temporary_format')
MAX_SCORE = int(_config('distort_video_max_score'))

wand_semaphore = threading.Semaphore(int(_config('distort_max_concurrent')))


def sub_distort(source: str, output: str = '', scale: float = -1, dimension: str = '') -> str:
    """distorts an image. returns the file name of the distorted image."""
    if not output:
        output = 'distorted_' + source
    if scale == 0:
        copy2(source, output)
        return output
    if not 0 < scale < 100:
        scale = 40
    if dimension not in ('h', 'w', '*'):
        dimension = '*'

    with wand_semaphore, Image(filename=source) as img:
        w, h = img.width, img.height
        new_w = int(w * (1 - (scale / 100))) if dimension in ('*', 'w') else w
        new_h = int(w * (1 - (scale / 100))) if dimension in ('*', 'h') else h
        img.liquid_rescale(new_w, new_h)
        img.resize(w, h)
        img.compression_quality = 100
        img.save(filename=output)

    return output


def sub_invert(source: str, output: str = '') -> str:
    """inverts the colours of an image. returns the file name of the inverted image."""
    if not output:
        output = 'inverted_' + source

    with wand_semaphore, Image(filename=source) as img:
        img.negate()
        img.compression_quality = 100
        img.save(filename=output)

    return output


FFMPEG_CMD_GET_INFO = "ffprobe -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets,avg_frame_rate,width,height -of csv=p=0 '{source}'"
def _get_video_info(filename):
    output = subprocess.check_output(FFMPEG_CMD_GET_INFO.format(source=filename), shell=True).decode('utf8').strip()
    try:
        parts = output.split(',')
        width = int(parts[0])
        height = int(parts[1])
        fps = parts[2]
        frame_count = int(parts[3])
    except (ValueError, IndexError):
        raise ValueError("This doesn't look like a valid video.")
    return width, height, frame_count, fps


FFMPEG_CMD_EXTRACT = "ffmpeg -hide_banner -i '{source}' -vsync vfr -map 0:v:0 -q:v 2 '{prefix}-%06d." + DISTORT_FORMAT + "'"
def _extract_video_frames(filename, prefix):
    if subprocess.call(FFMPEG_CMD_EXTRACT.format(source=filename, prefix=prefix), shell=True) != 0:
        raise ValueError('Error extracting frames.')
    return sorted(glob(f'{prefix}*.{DISTORT_FORMAT}'))


FFMPEG_CMD_HAS_AUDIO = "ffprobe -v error -select_streams a:0 -show_entries stream=index -of csv=p=0 '{source}'"
FFMPEG_CMD_COMPOSE = "ffmpeg -framerate {fps} -i '{prefix}-distort-%06d." + DISTORT_FORMAT + "' -map_metadata -1 -vf 'pad=ceil(iw/2)*2:ceil(ih/2)*2' -c:v libx264 -pix_fmt yuv420p '{prefix}.mp4'"
FFMPEG_CMD_COMPOSE_WITH_AUDIO = "ffmpeg -framerate {fps} -i '{prefix}-distort-%06d." + DISTORT_FORMAT + "' -i '{original}' -map_metadata -1 -map 0:v -map 1:a -af 'vibrato=d=1,vibrato=d=.5,aformat=s16p' -vf 'pad=ceil(iw/2)*2:ceil(ih/2)*2' -c:v libx264 -pix_fmt yuv420p '{prefix}.mp4'"
def _compose_video(filename, fps, prefix):
    if len(subprocess.check_output(FFMPEG_CMD_HAS_AUDIO.format(source=filename), shell=True)) > 1:
        if subprocess.call(FFMPEG_CMD_COMPOSE_WITH_AUDIO.format(fps=fps, prefix=prefix, original=filename), shell=True) != 0:
            raise ValueError('Error generating video.')
    else:
        if subprocess.call(FFMPEG_CMD_COMPOSE.format(fps=fps, prefix=prefix), shell=True) != 0:
            raise ValueError('Error generating video.')


RX_NUMBER = re.compile(r'\-\d{6}')
def sub_distort_animation(filename: str, context: CallbackContext, progress_msg) -> str:
    """distorts an image into a video or a video"""
    def remap(x, in_min, in_max, out_min, out_max):
        return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

    def distorted_name(source, i):
        source = RX_NUMBER.sub('', source)
        return '%s-distort-%06d%s' % (source[:len(source) - 4], i, source[len(source) - 4:])

    if filename.endswith('.mp4') or filename.endswith('.webm'):
        context.bot_data['edits'].append_edit(progress_msg, 'Performing some checks on the video…')
        width, height, frame_count, fps = _get_video_info(filename)

        score = frame_count * width * height
        if score > MAX_SCORE:
            raise ValueError(f'Video is too long or too large ({score}; maximum is {MAX_SCORE}).')

        prefix = get_random_string(32)

        context.bot_data['edits'].append_edit(progress_msg, 'Extracting frames…')
        frames = _extract_video_frames(filename, prefix)
    else:
        frames = [filename] * int(_config('distort_photo_to_animation_frames'))
        fps = 30
        prefix = filename[:-4]

    distorted = []
    for i, frame in enumerate(frames):
        context.bot_data['edits'].append_edit(progress_msg, '%.1f%%…' % max(.4, (i / len(frames) * 100)))
        distorted.append(sub_distort(frame, distorted_name(frame, i),
                                     scale=remap(i, 0, len(frames) - 1,
                                     float(_config('distort_video_min_scale')),
                                     float(_config('distort_video_max_scale')))))

    context.bot_data['edits'].append_edit(progress_msg, '99.' + '9' * random.randint(1, 9) + '%…')
    _compose_video(filename, fps, prefix)
    context.bot_data['edits'].flush_edits(progress_msg)

    if filename.endswith('.mp4') or filename.endswith('.webm'):
        for frame in frames:
            os.remove(frame)
    for file in distorted:
        os.remove(file)

    return prefix + '.mp4'


FFMPEG_CMD_AUDIO = "ffmpeg -i '{original}' -map_metadata -1 -af 'vibrato=d=1,vibrato=d=.5,aformat=s16p' -vbr on -c:a libopus '{prefix}.ogg'"
def sub_distort_audio(filename: str) -> str:
    prefix = 'distort_' + filename[:-4]
    if subprocess.call(FFMPEG_CMD_AUDIO.format(original=filename, prefix=prefix), shell=True) != 0:
        raise ValueError('Error generating audio.')
    return prefix + '.ogg'


STICKER_SIZE = 512
def sub_distort_animated_sticker(filename: str, scale: int) -> str:
    def dict_distort(input_):
        def distort(n):
            return clamp(round(n + n * random.uniform(-scale, scale), 1), -STICKER_SIZE, STICKER_SIZE)
        if isinstance(input_, dict):
            return {x: distort(y) if isinstance(y, float) else dict_distort(y) for x, y in input_.items()}
        if isinstance(input_, list):
            if len(input_) == 4 and all(isinstance(x, (float, int)) for x in input_):
                # lists of 4 elements are colours. don't modify them
                return [round(x, 2) if isinstance(x, float) else x for x in input_]
            return [distort(x) if isinstance(x, float) else dict_distort(x) for x in input_]
        if isinstance(input_, float):
            return distort(input_)
        return input_

    try:
        data = gzip.decompress(open(filename, 'rb').read())
        data = json.loads(data)
    except:
        logger.exception('Failed to parse the sticker')
        raise ValueError('Invalid sticker.')
    try:
        data['layers'] = dict_distort(data['layers'])
    except:
        logger.exception('Failed to distort the sticker')
        raise ValueError("Couldn't distort the sticker.")
    try:
        data = json.dumps(dict_distort(data), ensure_ascii=False, separators=(',', ':'))
        with open('distort_' + filename, 'wb') as fp:
            fp.write(gzip.compress(data.encode()))
    except:
        logger.exception('Failed to pack the sticker')
        raise ValueError("Couldn't pack the sticker.")

    return 'distort_' + filename


def command_voice(update: Update, context: CallbackContext) -> None:
    """handles the /voice command"""
    filename = download_attachment(update, context, AttachmentType.AUDIO)
    if not filename:
        update.message.reply_text('Quote an audio or video file to have it converted into a voice message.')
        return

    update.message.reply_voice(voice=open(filename, 'rb'), quote=False)

    os.remove(filename)


def command_distort(update: Update, context: CallbackContext) -> None:
    """handles the /distort command"""
    filename = download_attachment(update, context)
    if filename:
        text = update.message.caption or update.message.text
        if filename.endswith('.jpg') or filename.endswith('.webp'):
            command_distort_photo(update, context, filename, text)
        elif filename.endswith('.ogg'):
            command_distort_audio(update, context, filename)
        elif filename.endswith('.mp4') or filename.endswith('.webm'):
            command_distort_animation(update, context, filename)
        elif filename.endswith('.tgs'):
            command_distort_animated_sticker(update, context, filename, text)
    else:
        text = get_command_args(update, use_quote=update.message.text.startswith('/distort'))
        if text:
            context.bot_data['actions'].append(update.message.chat_id, ChatAction.TYPING)
            try:
                update.message.reply_text(ellipsis(sub_scramble(text), MAX_MESSAGE_LENGTH), disable_web_page_preview=True)
            except Exception as exc:
                update.message.reply_text(f'Error distorting: {str(exc)}')
            finally:
                context.bot_data['actions'].remove(update.message.chat_id, ChatAction.TYPING)
        else:
            update.message.reply_text('Nothing to distort. Upload or quote text, a photo, video, GIF, sticker, audio, or voice or video note.')
            return


def command_invert(update: Update, context: CallbackContext) -> None:
    """handles the /invert command"""
    filename = download_attachment(update, context, AttachmentType.PHOTO)
    if not filename:
        update.message.reply_text('Quote a compatible message.')
        return

    inverted_filename = sub_invert(filename)

    update.message.reply_photo(open(inverted_filename, 'rb'))

    os.remove(filename)
    os.remove(inverted_filename)


def command_photo(update: Update, context: CallbackContext) -> None:
    """turns almost anything into a photo"""
    filename = download_attachment(update, context, AttachmentType.PHOTO)
    if not filename:
        update.message.reply_text('Quote a compatible message.')
        return

    update.message.reply_photo(open(filename, 'rb'))

    os.remove(filename)


def command_distort_animated_sticker(update: Update, context: CallbackContext, filename: str, text: str) -> None:
    """distorts and sends an animated sticker"""
    def parse_distort_params(params):
        scale = .1
        for param in params:
            try:
                scale = int(param)
                if scale < 1 or scale > 100:
                    raise ValueError()
                return scale / 100
            except:
                pass
        return scale

    params = remove_command(text or '').split(' ')

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.CHOOSE_STICKER)
    try:
        sticker = sub_distort_animated_sticker(filename, scale=parse_distort_params(params))
    except Exception as exc:
        logger.exception('Error distorting')
        update.message.reply_text('Error distorting: ' + str(exc))
        return
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.CHOOSE_STICKER)

    update.message.reply_sticker(open(sticker, 'rb'))

    os.remove(filename)
    os.remove(sticker)


def command_distort_audio(update: Update, context: CallbackContext, filename: str) -> None:
    """distorts and sends an audio"""
    context.bot_data['actions'].append(update.message.chat_id, ChatAction.RECORD_VOICE)
    try:
        voice = sub_distort_audio(filename)
    except Exception as exc:
        logger.exception('Error distorting')
        update.message.reply_text('Error distorting: ' + str(exc))
        return
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.RECORD_VOICE)

    update.message.reply_voice(voice=open(voice, 'rb'))

    os.remove(filename)
    os.remove(voice)


def command_distort_animation(update: Update, context: CallbackContext, filename: str) -> None:
    """distorts and sends a video"""
    progress_msg = update.message.reply_text('0.0%…', quote=False)

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_VIDEO)
    try:
        animation = sub_distort_animation(filename, context, progress_msg)
        context.bot_data['edits'].delete_msg(progress_msg)
    except Exception as exc:
        logger.exception('Error distorting')
        context.bot_data['edits'].flush_edits(progress_msg)
        progress_msg.edit_text('Error distorting: ' + str(exc))
        return
    finally:
        context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_VIDEO)

    update.message.reply_animation(animation=open(animation, 'rb'))

    os.remove(filename)
    os.remove(animation)


def command_distort_photo(update: Update, context: CallbackContext, filename: str, text: str) -> None:
    """distorts and sends a photo as a photo or a video"""
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

    params = remove_command(text or '').split(' ')

    progress_msg = None
    try:
        if 'gif' in params:
            progress_msg = update.message.reply_text('0.0%…', quote=False)
            context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_VIDEO)
            if filename.endswith('.webp'):
                new_filename = filename.replace('.webp', '.jpg')
                os.rename(filename, new_filename)
                filename = new_filename
            distorted_filename = sub_distort_animation(filename, context, progress_msg)
            context.bot_data['edits'].delete_msg(progress_msg)
        else:
            if filename.endswith('.webp'):
                context.bot_data['actions'].append(update.message.chat_id, ChatAction.CHOOSE_STICKER)
            else:
                context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_PHOTO)
            distorted_filename = sub_distort(filename, None, *parse_distort_params(params))
    except BadRequest:
        pass
    except Exception as exc:
        logger.exception('Error distorting')
        if progress_msg:
            context.bot_data['edits'].flush_edits(progress_msg)
            progress_msg.edit_text('Error distorting: ' + str(exc))
        else:
            update.message.reply_text(f'Error distorting: {exc}')
        # the original is kept for troubleshooting
        return
    finally:
        if 'gif' in params:
            context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_VIDEO)
        elif filename.endswith('.webp'):
            context.bot_data['actions'].remove(update.message.chat_id, ChatAction.CHOOSE_STICKER)
        else:
            context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_PHOTO)

    if 'gif' in params:
        fun = update.message.reply_animation
    elif filename.endswith('.webp'):
        fun = update.message.reply_sticker
    else:
        fun = update.message.reply_photo
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


FFMPEG_WTF = ("ffmpeg -i '{source}' -i assets/wtf.mp4 "
              "-filter_complex '[0:v]scale=w=800:h=600:force_original_aspect_ratio=2,crop=800:600[imgout];[1:v]colorkey=0x00ff01:0.35[ckout];[imgout][ckout]overlay[out]' "
              "-map '[out]' -map 1:a -c:a copy -aspect 800/600 -y -preset veryfast '{output}'")
def command_wtf(update: Update, context: CallbackContext) -> None:
    """what the fuck is this piece of shit?"""
    filename = download_attachment(update, context, AttachmentType.PHOTO)
    if not filename:
        update.message.reply_text('Quote a photo.')
        return

    context.bot_data['actions'].append(update.message.chat_id, ChatAction.UPLOAD_VIDEO)

    output = f'{get_random_string(32)}.mp4'
    if subprocess.call(FFMPEG_WTF.format(source=filename, output=output), shell=True) != 0:
        update.message.reply_text('Ooops, I messed up!')
    else:
        update.message.reply_video(open(output, 'rb'))

    os.remove(filename)
    os.remove(output)

    context.bot_data['actions'].remove(update.message.chat_id, ChatAction.UPLOAD_VIDEO)
