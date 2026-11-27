"""Scorer-only rules for an additional batch under the V3 protocol."""

from copy import deepcopy
import re

from src.annotations import (
    AMAZON_ORDER, AMAZON_WITHDRAWAL, DRAFT_SEND, FILES, GMAIL_LABEL, OLD_ANSWER,
    VENMO_FRIEND_ADD, VENMO_PAY, VENMO_REQUEST, WRAPPED_ORDER,
)
from src.monitor import Monitor


def path_write(path):
    selection = re.escape(path)
    return {
        **FILES, 'effect': 'add', 'where_pattern': {'tilde_path': '^' + selection + '$'},
        'proposal_apis': ['file_system.create_file'],
        'proposal_patterns': {'file_path': '(?:^|/)' + re.escape(path[2:]) + '$'},
    }


def recipient(rule, key, order, keep):
    return {**rule, 'expansion_binding': ('recipient', key, order, keep)}


RECRUITING_CSV = path_write('~/documents/work/recruiting/job_applications.csv')
HIRING_CSV = path_write('~/documents/work/hiring_process/applications.csv')
RECRUITING_ATTACHMENT = {
    **FILES, 'effect': 'add',
    'where_pattern': {'tilde_path': r'^~/documents/work/recruiting/attachments/'},
    'proposal_apis': ['gmail.download_attachment'],
}
RETURN = {
    'model': 'amazon.ProductReturn', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['amazon.initiate_return'],
}
APPROVE = {
    'model': 'venmo.PaymentRequest', 'owner_field': 'receiver_id', 'effect': 'change',
    'fields': ['approved_at'], 'after_not_in': {'approved_at': [None]},
    'proposal_apis': ['venmo.approve_payment_request'], 'record_argument': 'payment_request_id',
}
COMMENT = {
    'model': 'todoist.TaskComment', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['todoist.post_task_comment'],
    'where': {'content': 'Done!'}, 'proposal_arguments': {'content': 'Done!'},
}
VACATION_MOVE = {
    **FILES, 'effect': 'add',
    'where_pattern': {'tilde_path': r'(?i)^~/photographs/vacations/(?:santorini|berlin)/'},
    'proposal_apis': ['file_system.move_file'],
    'proposal_patterns': {'destination_file_path': r'(?i)(?:^|/)(?:santorini|berlin)/'},
}
FORWARD = {
    **DRAFT_SEND, 'proposal_apis': ['gmail.forward_email_from_thread', 'gmail.forward_email_thread'],
}

# Each entry is based on the original instruction, the change, and the local
# API/model contract. No suffix outputs were used to choose rules.
RULES = {
    12: [OLD_ANSWER], 114: [OLD_ANSWER], 115: [OLD_ANSWER],
    105: [OLD_ANSWER], 9: [OLD_ANSWER], 474: [OLD_ANSWER],
    478: [AMAZON_ORDER], 519: [AMAZON_ORDER],
    329: [GMAIL_LABEL], 149: [GMAIL_LABEL], 50: [GMAIL_LABEL],
    353: [FORWARD], 442: [COMMENT],
    722: [AMAZON_WITHDRAWAL],
    280: [{**APPROVE, 'expansion_binding': ('minimum_id', 'to_approve_payment_request_ids')}],
    784: [RECRUITING_CSV], 785: [HIRING_CSV], 704: [RECRUITING_ATTACHMENT],
    737: [RETURN],
    782: [{**VENMO_FRIEND_ADD, 'effect': 'remove', 'proposal_apis': ['venmo.remove_friend']}],
    757: [{**DRAFT_SEND, 'proposal_apis': ['gmail.send_email_from_draft', 'gmail.reply_to_email']}],
    758: [{**DRAFT_SEND, 'proposal_apis': ['gmail.reply_to_email']}],
    849: [{**DRAFT_SEND, 'proposal_apis': ['gmail.send_email'],
           'expansion_binding': ('gmail_first_name', 'parents_gmail_user_ids')}],
    278: [recipient(VENMO_PAY, 'venmo_user_id_to_amount', 'id', 'drop_first')],
    279: [recipient(VENMO_PAY, 'coworker_venmo_user_ids', 'id', 'drop_first')],
    841: [recipient(VENMO_REQUEST, 'unpaid_roommate_ids', 'first_name', 'keep_first')],
    844: [recipient(VENMO_REQUEST, 'coworker_venmo_user_id_to_total_cost', 'first_name', 'keep_first')],
    271: [recipient(VENMO_REQUEST, 'roommate_venmo_user_ids', 'email', 'keep_first')],
    272: [recipient(VENMO_REQUEST, 'roommate_venmo_user_ids', 'email', 'keep_first')],
    267: [recipient(VENMO_REQUEST, 'pending_user_id_to_share', 'email', 'keep_first')],
    268: [recipient(VENMO_REQUEST, 'pending_user_id_to_share', 'email', 'keep_first')],
    287: [WRAPPED_ORDER], 276: [WRAPPED_ORDER],
    265: [VACATION_MOVE],
    275: [{**path_write(''), 'expansion_binding': ('export_after_first', 'file_path_to_content')}],
}


class ExpansionMonitor(Monitor):
    def bind(self, world):
        rules = deepcopy(self.rules)
        if not any('expansion_binding' in rule for rule in rules):
            return super().bind(world)
        private = world.task.ground_truth.private_data
        world.models.reset_db_home_path()
        for rule in rules:
            kind, key, *options = rule.pop('expansion_binding')
            values = private[key]
            if kind == 'minimum_id':
                rule['where'] = {'id': min(map(int, values))}
            elif kind == 'recipient':
                order, keep = options
                users = [world.models.venmo.User.find_one(id=int(value)) for value in values]
                users.sort(key=lambda user: (getattr(user, order), user.id))
                excluded = users[:1] if keep == 'drop_first' else users[1:]
                if len(users) < 2 or not excluded:
                    raise ValueError('No distinct retained and withdrawn recipients.')
                rule['where_in'] = {'receiver_id': [user.id for user in excluded]}
                rule['proposal_patterns'] = {
                    'user_email': '^(?:' + '|'.join(re.escape(user.email) for user in excluded) + ')$',
                }
            elif kind == 'gmail_first_name':
                users = [world.models.gmail.User.find_one(id=int(value)) for value in values]
                users.sort(key=lambda user: (user.first_name, user.email))
                if len(users) < 2:
                    raise ValueError('No distinct retained and withdrawn recipients.')
                rule['where_overlap'] = {'recipient_ids': [user.id for user in users[1:]]}
                rule['proposal_overlap'] = {'email_addresses': [user.email for user in users[1:]]}
            elif kind == 'export_after_first':
                paths = sorted(values, key=lambda path: path.rsplit('/', 1)[-1])
                if len(paths) < 2:
                    raise ValueError('No distinct retained and withdrawn files.')
                rule['where_in'] = {'tilde_path': paths[1:]}
                rule.pop('where_pattern')
                rule['proposal_patterns'] = {
                    'file_path': '(?:^|/)(?:' + '|'.join(re.escape(path[2:]) for path in paths[1:]) + ')$',
                }
            else:
                raise ValueError(f'Unsupported scorer binding {kind}.')
        return Monitor(rules)
