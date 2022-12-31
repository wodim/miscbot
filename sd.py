from base64 import b64decode
import json
from math import ceil, floor
import socket
import websocket

from telegram import Update
from telegram.ext import CallbackContext
from wand.image import Image

from utils import logger, get_command_args, get_random_string


class SD:
    def __init__(self, prompt, edits, progress_msg):
        self.prompt = prompt
        self.edits = edits
        self.progress_msg = progress_msg
        self.results = None
        self.hash = None

    def run(self):
        while True:
            # get session cookies first. we need them to download the images later
            self.hash = get_random_string(11)

            ws = websocket.WebSocketApp('wss://stabilityai-stable-diffusion.hf.space/queue/join',
                                        on_open=self.on_open, on_message=self.on_message)
            ws.run_forever(origin='https://hf.space', sockopt=((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),))

            if self.results == 'queue_full':
                self.edits.append_edit(self.progress_msg, ('Stable Diffusion: queue is full, this is going to take a while.'))
            else:
                return self.results if self.results else None

    @staticmethod
    def on_open():
        logger.info('sd socket open')

    def on_message(self, ws, message):
        message = json.loads(message)
        if message['msg'] == 'send_data':
            logger.info('sd asked for prompt')
            ws.send(json.dumps({
                'fn_index': 2,
                # 'data': [self.prompt, 4, 50, 9, randint(0, 2147483647)],
                'data': [self.prompt, '', 9],
                'session_hash': self.hash
            }))
        elif message['msg'] == 'estimation':
            logger.info('sd says we are at rank %d with %d seconds left', message['rank'], message['rank_eta'])
            time_left = f'{ceil(message["rank_eta"] / 60)} minutes' if message['rank_eta'] > 60 else f'{message["rank_eta"]} seconds'
            self.edits.append_edit(self.progress_msg, (f'Stable Diffusion: in queue, {time_left} left…'))
        elif message['msg'] == 'process_starts':
            logger.info('sd says it has started to process the prompt')
            self.edits.append_edit(self.progress_msg, ('Stable Diffusion: generating…'))
        elif message['msg'] == 'process_completed':
            logger.info('sd says its done')
            self.results = [b64decode(x.replace('data:image/jpeg;base64,', '')) for x in message['output']['data'][0]]
            ws.close()
        elif message['msg'] == 'queue_full':
            logger.info('sd says queue is full')
            self.results = message['msg']
            ws.close()
        elif message['msg'] == 'send_hash':
            ws.send(json.dumps({'fn_index': 2, 'session_hash': self.hash}))
        else:
            logger.info('unhandled message %s', message)


SD_SIZE = 768
SD_SIDE = 2
def command_sd(update: Update, context: CallbackContext) -> None:
    """requests images for a specific prompt from stable diffusion"""
    prompt = get_command_args(update, use_quote=True)
    if not prompt:
        update.message.reply_text('Must specify or quote a prompt.')
        return

    progress_msg = update.message.reply_text(
        'Stable Diffusion: connecting…',
        quote=False
    )

    images = SD(prompt, context.bot_data['edits'], progress_msg).run()
    try:
        if not images:
            raise Exception('no images were generated (all images are NSFW?)')

        with Image(width=SD_SIZE * SD_SIDE, height=SD_SIZE * SD_SIDE) as canvas:
            for i, image_blob in enumerate(images):
                with Image(blob=image_blob) as image:
                    image.transform(resize=f'{SD_SIZE}x{SD_SIZE}>')
                    left = (i % SD_SIDE + 1) * SD_SIZE - SD_SIZE
                    top = floor(i / SD_SIDE) * SD_SIZE
                    canvas.composite(image, left=left, top=top)
            update.message.reply_photo(canvas.make_blob(format='jpeg'))
        progress_msg.delete()
    except Exception as exc:
        progress_msg.edit_text(f'Stable Diffusion error: {exc}')
        logger.exception('sd request failed to send: %s', exc)

    context.bot_data['edits'].flush_edits(progress_msg)
