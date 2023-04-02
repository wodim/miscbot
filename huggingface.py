from base64 import b64decode, b64encode
from enum import Enum, auto
import json
from math import ceil, floor
import os
import socket
import time

from telegram import Update
from telegram.ext import CallbackContext
from wand.image import Image
import websocket

from attachments import AttachmentType, download_attachment
from utils import get_command_args, get_random_string, is_admin, logger, requests_session


class HuggingFaceFormat(Enum):
    TEXT = auto()
    PHOTO = auto()
    VIDEO = auto()
    ANIMATION = auto()


def from_b64(s):
    s = s.replace('data:image/png;base64,', '')
    s = s.replace('data:image/jpeg;base64,', '')
    return b64decode(s)


def to_b64(i):
    return 'data:image/jpeg;base64,' + b64encode(i).decode('utf-8')


class HuggingFaceWS:
    def __init__(self, edits, progress_msg, data):
        self.edits = edits
        self.progress_msg = progress_msg
        self.data = data
        self.data['fn_index'] = self.data.get('fn_index') or 0
        self.results = None
        self.hash = None

    def run(self):
        for _ in range(self.data['times']):
            while True:
                self.hash = get_random_string(11)
                ws = websocket.WebSocketApp(f'wss://{self.data["space"]}.hf.space/queue/join',
                                            on_message=self.on_message, on_open=self.on_open, on_close=self.on_close)
                ws.run_forever(origin=f'https://{self.data["space"]}.hf.space', sockopt=((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),))

                if self.results == 'queue_full' and self.progress_msg:
                    self.edits.append_edit(self.progress_msg, (f'{self.data["name"]}: queue is full, this is going to take a while.'))
                else:
                    break

            if self.data['times'] > 1:
                # refeed
                for k, v in enumerate(self.data['in_format']):
                    if isinstance(v, str) and v.startswith('data:'):
                        # some effects increase the size of an image. don't let it go out of hand
                        with Image(blob=from_b64(self.results)) as image:
                            if image.width > 1280 or image.height > 1280:
                                image.transform(resize='1280x1280>')
                                self.results = to_b64(image.make_blob(format='jpeg'))
                        self.data['in_format'][k] = self.results

        return self.results

    def on_open(self, ws):
        logger.info('%s: connected', self.data['name'])
        if self.data.get('hash_on_open'):
            logger.info('%s: sending on_open hash', self.data['name'])
            ws.send(json.dumps({'hash': self.hash}))

    def on_close(self, *_):
        logger.info('%s: socket closed', self.data['name'])

    def on_message(self, ws, message):
        message = json.loads(message)
        if message['msg'] == 'send_data':
            logger.info('%s asked for data', self.data['name'])
            ws.send(json.dumps({
                'fn_index': self.data['fn_index'],
                'data': self.data['in_format'],
                'session_hash': self.hash
            }))
        elif message['msg'] == 'estimation':
            if message.get('rank') and message.get('rank_eta'):
                logger.info('%s says we are at rank %d with %d seconds left', self.data['name'], message['rank'], message['rank_eta'])
                time_left = f'{ceil(message["rank_eta"] / 60)} minutes' if message['rank_eta'] > 60 else f'{ceil(message["rank_eta"])} seconds'
                if self.progress_msg:
                    self.edits.append_edit(self.progress_msg, (f'{self.data["name"]}: in queue, {time_left} left…'))
            else:
                if self.progress_msg:
                    self.edits.append_edit(self.progress_msg, (f'{self.data["name"]}: in queue…'))
        elif message['msg'] == 'process_starts':
            logger.info('%s says it has started to process the prompt', self.data['name'])
            if self.progress_msg:
                self.edits.append_edit(self.progress_msg, (f'{self.data["name"]}: generating…'))
        elif message['msg'] == 'process_completed':
            logger.info('%s says its done', self.data['name'])
            try:
                self.results = message['output']['data'][0]
            except KeyError:
                self.results = None
            ws.close()
        elif message['msg'] == 'queue_full':
            logger.info('%s says queue is full', self.data['name'])
            self.results = message['msg']
            ws.close()
        elif message['msg'] == 'send_hash':
            ws.send(json.dumps({'fn_index': self.data['fn_index'], 'session_hash': self.hash}))
        else:
            logger.info('unhandled message %s', message)


class HuggingFacePush:
    def __init__(self, edits, progress_msg, data):
        self.edits = edits
        self.progress_msg = progress_msg
        self.data = data
        self.data['fn_index'] = self.data.get('fn_index') or 0
        self.results = None
        self.hash = None

    def run(self):
        for _ in range(self.data['times']):
            self.hash = get_random_string(11)
            logger.info('%s: getting hash', self.data['name'])
            r = requests_session.post(f'https://{self.data["space"]}.hf.space/api/queue/push/', json={
                'fn_index': self.data['fn_index'],
                'data': self.data['in_format'],
                'action': 'predict',
                'session_hash': self.hash,
            }).json()
            hash_ = r['hash']

            while True:
                r = requests_session.post(f'https://{self.data["space"]}.hf.space/api/queue/status/', json={
                    'hash': hash_,
                }).json()

                if r['status'] == 'COMPLETE':
                    logger.info('%s: complete', self.data['name'])
                    if self.data['out_format'] == HuggingFaceFormat.PHOTO:
                        self.results = r['data']['data'][0]
                        break
                    elif self.data['out_format'] == HuggingFaceFormat.TEXT:
                        self.results = r['data']['data'][0]
                        break
                    else:
                        # TODO more formats
                        return
                elif r['status'] == 'PENDING':
                    logger.info('%s: pending', self.data['name'])
                    self.edits.append_edit(self.progress_msg, (f'{self.data["name"]}: pending…'))
                elif r['status'] == 'QUEUED':
                    logger.info('%s: in queue', self.data['name'])
                    self.edits.append_edit(self.progress_msg, (f'{self.data["name"]}: queued…'))
                else:
                    logger.info('%s: unknown status "%s"', self.data['name'], r['status'])

                time.sleep(.5)

            if self.data['times'] > 1:
                # refeed
                for k, v in enumerate(self.data['in_format']):
                    if isinstance(v, str) and v.startswith('data:'):
                        # some effects increase the size of an image. don't let it go out of hand
                        with Image(blob=from_b64(self.results)) as image:
                            if image.width > 1280 or image.height > 1280:
                                image.transform(resize='1280x1280>')
                                self.results = to_b64(image.make_blob(format='jpeg'))
                        self.data['in_format'][k] = self.results

        return self.results


def huggingface(update: Update, context: CallbackContext, data) -> None:
    """huggingface generic implementation"""
    # first, we have to check if we have what we need as specified by the format
    for k, v in enumerate(data['in_format']):
        if v == HuggingFaceFormat.PHOTO:
            photo = download_attachment(update, context, AttachmentType.PHOTO)
            if not photo:
                update.message.reply_text('This command requires a photo. Post or quote one.')
                return
            with open(photo, 'rb') as fp:
                data['in_format'][k] = to_b64(fp.read())
            os.remove(photo)
        elif v == HuggingFaceFormat.TEXT:
            data['in_format'][k] = get_command_args(update, use_quote=True)
            if not data['in_format'][k]:
                update.message.reply_text('This command requires text. Post or quote some.')
                return

    data['times'] = 1
    if data.get('multiple'):
        try:
            data['times'] = int(get_command_args(update, use_quote=False))
            if not is_admin(update.message.from_user.id) and (data['times'] < 1 or data['times'] > 100):
                data['times'] = 1
        except (TypeError, ValueError):
            pass

    progress_msg = update.message.reply_text(
        f'{data["name"]}: connecting…',
        quote=False
    )

    cls = HuggingFacePush if data.get('method') == 'push' else HuggingFaceWS
    result = cls(context.bot_data['edits'], progress_msg, data).run()

    if result:
        if data['out_format'] == HuggingFaceFormat.PHOTO:
            result = from_b64(result)
        elif data['out_format'] == [HuggingFaceFormat.PHOTO]:
            result = [from_b64(x) for x in result]
        elif data['out_format'] == HuggingFaceFormat.TEXT:
            pass
        else:
            raise ValueError(f'unknown output format for {data["name"]}')

        if data['out_format'] == HuggingFaceFormat.PHOTO:
            with Image(blob=result) as image:
                if image.width > 1280 or image.height > 1280:
                    image.transform(resize=f'{1280}x{1280}>')
                    update.message.reply_photo(image.make_blob(format='jpeg'))
                else:
                    update.message.reply_photo(result)
        elif data['out_format'] == [HuggingFaceFormat.PHOTO]:
            # TODO: dehardcode
            SD_SIZE = 768
            SD_SIDE = 2
            with Image(width=SD_SIZE * SD_SIDE, height=SD_SIZE * SD_SIDE) as canvas:
                for i, image_blob in enumerate(result):
                    with Image(blob=image_blob) as image:
                        image.transform(resize=f'{SD_SIZE}x{SD_SIZE}>')
                        left = (i % SD_SIDE + 1) * SD_SIZE - SD_SIZE
                        top = floor(i / SD_SIDE) * SD_SIZE
                        canvas.composite(image, left=left, top=top)
                update.message.reply_photo(canvas.make_blob(format='jpeg'))
        elif data['out_format'] == HuggingFaceFormat.TEXT:
            update.message.reply_text(result)
        progress_msg.delete()
    else:
        progress_msg.edit_text(f'{data["name"]}: failed.')

    context.bot_data['edits'].flush_edits(progress_msg)
