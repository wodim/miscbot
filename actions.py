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

    def remove(self, chat_id, action):
        try:
            self.pending_actions.remove((chat_id, action))
        except ValueError:
            pass

        # sending a message clears the current action, so check if there are
        # more actions for this chat_id and send the latest one immediately
        # (the same thing cron does) -- a small delay is necessary, otherwise
        # this won't work, so we need the job queue
        if chat_id in dict(self.pending_actions).keys():
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
            return f'pending actions: {self.pending_actions}'
        return 'no pending actions'
