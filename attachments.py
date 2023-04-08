from enum import Enum, auto
import os
import subprocess

from wand.image import Image

from utils import get_random_string


class AttachmentType(Enum):
    PHOTO = auto()
    VIDEO = auto()
    STICKER_STATIC = auto()
    STICKER_ANIMATED = auto()
    AUDIO = auto()
    DOCUMENT = auto()


def _download_anything(message, context):
    def download(obj, extension):
        return context.bot.get_file(obj).download(custom_path=f'{get_random_string(12)}.{extension}')

    if getattr(message, 'photo'):
        return download(message.photo[-1], 'jpg')
    if getattr(message, 'animation'):
        return download(message.animation, 'mp4')
    if getattr(message, 'video'):
        return download(message.video, 'mp4')
    if getattr(message, 'sticker'):
        if message.sticker.is_animated:
            return download(message.sticker, 'tgs')
        filename = download(message.sticker, 'webp')
        with open(filename, 'rb') as fp:
            if fp.read(4) == b'RIFF':
                return filename
            new_filename = f'{filename}.webm'
            os.rename(filename, new_filename)
            return new_filename
    if getattr(message, 'voice'):
        return download(message.voice, 'ogg')
    if getattr(message, 'video_note'):
        return download(message.video_note, 'mp4')
    if getattr(message, 'audio'):
        return download(message.audio, 'ogg')


VIDEO_TO_PHOTO_CMD = r"""ffmpeg -i '{filename}' -vf select=eq\(n\\,0\) '{filename}.jpg'"""
def _video_to_photo(filename: str) -> str:
    if subprocess.call(VIDEO_TO_PHOTO_CMD.format(filename=filename), shell=True) != 0:
        return None
    os.remove(filename)
    return f'{filename}.jpg'


VIDEO_TO_VOICE = "ffmpeg -i '{filename}' -map_metadata -1 -af 'aformat=s16p' -vbr on -c:a libopus '{filename}.ogg'"
def _video_to_voice(filename: str) -> str:
    if subprocess.call(VIDEO_TO_VOICE.format(filename=filename), shell=True) != 0:
        return None
    os.remove(filename)
    return filename + '.ogg'


def download_attachment(update, context, type_: AttachmentType=None):
    """downloads an attachment from a message or a quoted message,
        converting to the target type if necessary
        TODO needs to implement remaining types"""
    message = update.message.reply_to_message or update.message
    if not type_:
        return _download_anything(message, context)
    if type_ == AttachmentType.PHOTO:
        if getattr(message, 'photo'):
            return _download_anything(message, context)
        if getattr(message, 'sticker'):
            if message.sticker.is_animated:
                # can't be converted
                return None
            filename = _download_anything(message, context)
            if filename.endswith('.webp'):
                filename = _download_anything(message, context)
                img = Image(filename=filename)
                img.compression_quality = 100
                img.save(filename=filename + '.jpg')
                img.destroy()
                img.close()
                os.remove(filename)
                return filename + '.jpg'
            if filename.endswith('.webm'):
                return _video_to_photo(filename)
        if (getattr(message, 'video') or getattr(message, 'animation') or
                getattr(message, 'video_note')):
            return _video_to_photo(_download_anything(message, context))
    if type_ == AttachmentType.AUDIO:
        if (getattr(message, 'video') or getattr(message, 'audio') or
                getattr(message, 'voice') or getattr(message, 'video_note')):
            return _video_to_voice(_download_anything(message, context))
