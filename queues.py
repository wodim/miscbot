from telegram.error import BadRequest


class Actions:
    """this class handles all chat actions: stores thems and sends them
    periodically using a cron method"""
    def __init__(self, bot, job_queue):
        self.pending_actions = []
        self.bot = bot
        self.job_queue = job_queue

    def append(self, chat_id, action):
        self.pending_actions.append((chat_id, action))
        # send it immediately - don't wait for next cron
        self.bot.send_chat_action(chat_id=chat_id, action=action)
        self.job_queue.get_jobs_by_name('actions')[0].enabled = True

    def remove(self, chat_id, action):
        try:
            self.pending_actions.remove((chat_id, action))
        except ValueError:
            pass
        if len(self.pending_actions) == 0:
            self.job_queue.get_jobs_by_name('actions')[0].enabled = False

        # sending a message clears the current action, so check if there are
        # more actions for this chat_id and send the latest one immediately
        # (the same thing cron does) -- a small delay is necessary, otherwise
        # this won't work, so we need the job queue
        if chat_id in dict(self.pending_actions):
            self.job_queue.run_once(
                lambda context: self.bot.send_chat_action(chat_id=context.job.context[0],
                                                          action=context.job.context[1]),
                .1,  # 100 msec
                context=(chat_id, dict(self.pending_actions)[chat_id])
            )

    def flush(self):
        self.pending_actions = []

    def cron(self, _):
        """checks which chats have pending actions (typing/sending photo) and
        sends them"""
        # turn it into a dict so there is only one value per key
        for chat_id, action in dict(self.pending_actions).items():
            self.bot.send_chat_action(chat_id=chat_id, action=action)

    def dump(self) -> str:
        if self.pending_actions:
            return f'Pending actions: {self.pending_actions}'
        return 'No pending actions.'


class Edits:
    """this class handles pending edits and sends them in a staggered way"""
    def __init__(self, bot, job_queue):
        self.pending_edits = []
        self.last_edit = {}
        self.bot = bot
        self.job_queue = job_queue

    def append_edit(self, message, text):
        self.pending_edits.append((message, text))
        self.job_queue.get_jobs_by_name('edits')[0].enabled = True

    def flush(self):
        self.pending_edits = []
        self.last_edit = {}
        self.job_queue.get_jobs_by_name('edits')[0].enabled = False

    def flush_edits(self, message):
        self.pending_edits = list(filter(lambda x: x[0] != message, self.pending_edits))
        if message in self.last_edit:
            del self.last_edit[message]
        if len(self.pending_edits) == 0:
            self.job_queue.get_jobs_by_name('edits')[0].enabled = False

    def delete_msg(self, message):
        while True:
            try:
                self.flush_edits(message)
                message.delete()
                return
            except BadRequest:
                # this message was deleted already
                return
            except:
                pass

    def cron(self, _):
        """checks which messages have pending edits and sends them"""
        # turn it into a dict so there is only one value per key
        for message, text in dict(self.pending_edits).items():
            try:
                if message in self.last_edit and self.last_edit[message] != text:
                    message.edit_text(text)
                self.last_edit[message] = text
            except BadRequest:
                # this message was deleted
                self.flush_edits(message)
            except:
                # generally fails because of ratelimits
                pass

    def dump(self) -> str:
        if self.pending_edits:
            edits = {f'{x[0].message_id}@{x[0].chat_id}': x[1] for x in self.pending_edits}
            return f'Pending edits: {edits}'
        return 'No pending edits.'
