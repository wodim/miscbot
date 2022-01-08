class Actions:
    """this class handles all chat actions: stores thems and sends them
    periodically using a cron method"""
    def __init__(self, bot):
        self.pending_actions = []
        self.bot = bot

    def append(self, chat_id, action):
        self.pending_actions.append((chat_id, action))
        # send it immediately - don't wait for next cron
        self.bot.send_chat_action(chat_id=chat_id, action=action)

    def remove(self, chat_id, action):
        try:
            self.pending_actions.remove((chat_id, action))
        except ValueError:
            pass

    def cron(self, _):
        """checks which chats have pending actions (typing/sending photo) and
        sends them"""
        # turn it into a dict so there is only one value per key
        for chat_id, action in dict(self.pending_actions).items():
            self.bot.send_chat_action(chat_id=chat_id, action=action)

    def dump(self) -> str:
        if self.pending_actions:
            return 'pending actions: %s\nunique: %s' % (
                self.pending_actions,
                dict(self.pending_actions)
            )
        return 'no pending actions'
