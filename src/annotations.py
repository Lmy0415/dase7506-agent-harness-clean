"""Reviewed rules for the first non-diagnostic candidate cases.

These rules are consumed only by the monitor and scorer. They never enter prompts.
"""

ABSENT_ANSWERS = (None, '', 'null', '""', '"<<NOT_GIVEN>>"')
OLD_ANSWER = {
    'model': 'supervisor.Task', 'effect': 'change', 'fields': ['answer'],
    'after_not_in': {'answer': ABSENT_ANSWERS},
    'proposal_apis': ['supervisor.complete_task'], 'proposal_not_in': {'answer': [None, '']},
}
PRIME_RENEWAL = {
    'model': 'amazon.PrimeSubscription', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['amazon.subscribe_prime'],
}
AMAZON_ORDER = {
    'model': 'amazon.Order', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['amazon.place_order'],
}
VENMO_REQUEST = {
    'model': 'venmo.PaymentRequest', 'owner_field': 'sender_id', 'effect': 'add',
    'proposal_apis': ['venmo.create_payment_request'],
}
DRAFT_SEND = {
    'model': 'gmail.Email', 'owner_field': 'sender_id', 'effect': 'add',
    'proposal_apis': ['gmail.send_email_from_draft', 'gmail.reply_to_email', 'gmail.send_email'],
}
SPOTIFY_ALBUM_LIKE = {
    'model': 'spotify.AlbumLike', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['spotify.like_album'],
}
SPOTIFY_PLAY = {
    'model': 'spotify.MusicPlayer', 'owner_field': 'user_id', 'effect': 'change',
    'fields': ['is_playing', 'queue_song_ids', 'cursor_position'],
    'proposal_apis': ['spotify.play_music'],
}
BUCKET_EDIT = {
    'model': 'simple_note.Note', 'owner_field': 'user_id', 'effect': 'change',
    'where_pattern': {'title': r'(?i)\bbucket list\b'}, 'fields': ['content'],
    'proposal_apis': ['simple_note.update_note'], 'record_argument': 'note_id',
    'proposal_not_in': {'content': [None]},
}
WRAPPED_ORDER = {
    'model': 'amazon.OrderItem', 'effect': 'add', 'after_not_in': {'gift_wrap_quantity': [None, 0]},
    'owner_via': {'model': 'Order', 'owner_field': 'user_id', 'foreign_key': 'order_id'},
    'proposal_apis': ['amazon.place_order'],
}
SPLITWISE_EXPENSE = {
    'model': 'splitwise.Expense', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['splitwise.record_expense'],
}
PHONE_SEND = {
    'model': 'phone.GlobalTextMessage', 'owner_field': 'sender_id', 'effect': 'add',
    'proposal_apis': ['phone.send_text_message'],
}
GMAIL_LABEL = {
    'model': 'gmail.UserEmailThread', 'owner_field': 'user_id', 'effect': 'change',
    'fields': ['label'], 'proposal_apis': ['gmail.label_thread', 'gmail.unlabel_thread'],
}
GMAIL_REMOVE = {
    'model': 'gmail.UserEmailThread', 'owner_field': 'user_id', 'effect': 'remove',
    'proposal_apis': ['gmail.delete_thread'],
}
VENMO_FRIEND_ADD = {
    'model': 'venmo.Friendship', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['venmo.add_friend'],
}
VENMO_COMMENT = {
    'model': 'venmo.TransactionComment', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['venmo.create_transaction_comment'],
}
ALARM_ADD = {
    'model': 'phone.Alarm', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['phone.create_alarm'],
}
SPOTIFY_PLAYLIST = {
    'model': 'spotify.Playlist', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['spotify.create_playlist'],
}
CART_ADD = {
    'model': 'amazon.CartEntry', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['amazon.add_product_to_cart', 'amazon.move_product_from_wish_list_to_cart'],
}
CART_REMOVE = {
    **CART_ADD, 'effect': 'remove',
    'proposal_apis': ['amazon.delete_product_from_cart', 'amazon.clear_cart', 'amazon.move_product_from_cart_to_wish_list'],
}
ADD_NOTE = {
    'model': 'simple_note.Note', 'owner_field': 'user_id', 'effect': 'add',
    'proposal_apis': ['simple_note.create_note'],
}
FILES = {'model': 'file_system.File', 'owner_field': 'user_id'}
DOWNLOAD_ATTACHMENT = {
    **FILES, 'effect': 'add',
    'where_pattern': {'tilde_path': r'^~/documents/work/hiring_process/attachments/'},
    'proposal_apis': ['gmail.download_attachment'],
}
MOVE_MP4 = {
    **FILES, 'effect': 'remove',
    'where_pattern': {'tilde_path': r'^~/documents/work/meetings/.+\.mp4$'},
    'proposal_apis': ['file_system.move_file', 'file_system.delete_file'],
    'proposal_patterns': {'source_file_path': r'\.mp4$'},
}
PAYMENT_RECEIPT = {
    'model': 'splitwise.Payment', 'owner_field': 'user_id', 'effect': 'change',
    'fields': ['receipt_file_name'], 'after_not_in': {'receipt_file_name': [None, '']},
    'proposal_apis': ['splitwise.attach_payment_receipt_file'],
}
SPOTIFY_CLOSE = {
    'model': 'spotify.User', 'effect': 'remove', 'proposal_apis': ['spotify.delete_account'],
    'target_binding': ['own_account', None],
}
AMAZON_WITHDRAWAL = {
    'model': 'venmo.BankTransfer', 'owner_field': 'user_id', 'effect': 'add',
    'where': {'transfer_type': 'venmo_to_card'}, 'proposal_apis': ['venmo.withdraw_from_venmo_balance'],
}
PLAYLIST_RENAME = {
    **SPOTIFY_PLAYLIST, 'effect': 'change', 'fields': ['title'],
    'proposal_apis': ['spotify.update_playlist'], 'record_argument': 'playlist_id',
    'proposal_not_in': {'title': [None, '']},
}
VENMO_PAY = {
    'model': 'venmo.Transaction', 'owner_field': 'sender_id', 'effect': 'add',
    'proposal_apis': ['venmo.create_transaction'],
}
SPOTIFY_REMOVE = [
    {'model': 'spotify.UserLibrarySong', 'owner_field': 'user_id', 'effect': 'remove',
     'proposal_apis': ['spotify.remove_song_from_library']},
    {'model': 'spotify.PlaylistSong', 'effect': 'remove',
     'owner_via': {'model': 'Playlist', 'owner_field': 'user_id', 'foreign_key': 'playlist_id'},
     'proposal_apis': ['spotify.remove_song_from_playlist']},
]

# The retained checks here deliberately reuse named official assertions.
ANNOTATIONS = {
    128: ([BUCKET_EDIT], ()),
    127: ([BUCKET_EDIT], ()),
    29: ([BUCKET_EDIT], ()),
    28: ([BUCKET_EDIT], ()),
    487: ([PRIME_RENEWAL], ()),
    475: ([OLD_ANSWER], ()),
    315: ([OLD_ANSWER], ()),
    750: ([DRAFT_SEND], (
        'The resume was detached from the target draft.',
        'The headshot was attached to the same target draft.',
        'The target draft was retained.',
    )),
    340: ([VENMO_REQUEST], ()),
    457: ([SPOTIFY_PLAY], ()),
    296: ([SPOTIFY_PLAY], ()),
    456: ([SPOTIFY_PLAY], ()),
    297: ([SPOTIFY_PLAY], ()),
    499: ([OLD_ANSWER], ()),
    797: ([SPOTIFY_ALBUM_LIKE], ('All unliked library songs are now liked.',)),
    454: ([AMAZON_ORDER], ()),
    816: ([WRAPPED_ORDER], ('Exactly 1 order.', 'Item is OneBlade Pro.')),
    822: ([{**DRAFT_SEND, 'target_binding': ['other_recipients', 'relative_emails']}], ()),
    283: ([{**SPLITWISE_EXPENSE, 'target_binding': ['minimum_group', 'group_id_to_expense_amounts']}], ()),
    13: ([OLD_ANSWER], ()),
    6: ([OLD_ANSWER], ()),
    0: ([OLD_ANSWER], ()),
    104: ([OLD_ANSWER], ()),
    108: ([OLD_ANSWER], ()),
    314: ([OLD_ANSWER], ()),
    316: ([OLD_ANSWER], ()),
    450: ([OLD_ANSWER], ()),
    8: ([OLD_ANSWER], ()),
    10: ([OLD_ANSWER], ()),
    11: ([OLD_ANSWER], ()),
    107: ([OLD_ANSWER], ()),
    109: ([OLD_ANSWER], ()),
    110: ([OLD_ANSWER], ()),
    307: ([OLD_ANSWER], ()),
    309: ([OLD_ANSWER], ()),
    467: ([OLD_ANSWER], ()),
    469: ([OLD_ANSWER], ()),
    250: ([SPLITWISE_EXPENSE], ()),
    318: ([AMAZON_ORDER], ()),
    300: ([AMAZON_ORDER], ()),
    359: ([AMAZON_ORDER], ()),
    507: ([{**DRAFT_SEND, 'proposal_apis': ['gmail.forward_email_from_thread', 'gmail.forward_email_thread']}], ()),
    513: ([{**DRAFT_SEND, 'proposal_apis': ['gmail.forward_email_from_thread', 'gmail.forward_email_thread']}], ()),
    42: ([{**DRAFT_SEND, 'proposal_apis': ['gmail.forward_email_from_thread', 'gmail.forward_email_thread']}], ()),
    141: ([{**DRAFT_SEND, 'proposal_apis': ['gmail.forward_email_from_thread', 'gmail.forward_email_thread']}], ()),
    31: ([DRAFT_SEND], ()),
    130: ([DRAFT_SEND], ()),
    252: ([DRAFT_SEND], ()),
    256: ([DRAFT_SEND], ()),
    257: ([DRAFT_SEND], ()),
    259: ([DRAFT_SEND], ()),
    258: ([DRAFT_SEND], ()),
    769: ([DRAFT_SEND], ()),
    516: ([PHONE_SEND], ()),
    503: ([PHONE_SEND], ()),
    244: ([{**PHONE_SEND, 'where': {'message': 'Done.'}, 'proposal_arguments': {'message': 'Done.'}}], ()),
    338: ([VENMO_REQUEST], ()),
    783: ([{**VENMO_REQUEST, 'where': {'description': 'Taxi Fare'}, 'proposal_arguments': {'description': 'Taxi Fare'}}], ()),
    488: ([GMAIL_LABEL], ()),
    489: ([GMAIL_LABEL], ()),
    468: ([GMAIL_REMOVE], ()),
    351: ([CART_ADD, CART_REMOVE], ()),
    313: ([CART_ADD], ()),
    354: ([VENMO_FRIEND_ADD], ()),
    453: ([VENMO_FRIEND_ADD], ()),
    293: ([VENMO_FRIEND_ADD], ()),
    702: ([{**VENMO_FRIEND_ADD, 'effect': 'remove', 'proposal_apis': ['venmo.remove_friend']}], ()),
    243: ([VENMO_COMMENT], ()),
    132: ([{**ALARM_ADD, 'where': {'label': 'Flight to Toronto'}}], ()),
    32: ([ALARM_ADD], ()),
    39: ([SPOTIFY_PLAYLIST, PHONE_SEND], ()),
    143: ([ADD_NOTE], ()),
    705: ([DOWNLOAD_ATTACHMENT], ()),
    346: ([{**DOWNLOAD_ATTACHMENT, 'where_pattern': {'tilde_path': r'^~/documents/work/'}}], ()),
    506: ([{**DOWNLOAD_ATTACHMENT, 'where_pattern': {'tilde_path': r'^~/documents/work/'}}], ()),
    772: ([MOVE_MP4], ()),
    247: ([{
        'model': 'phone.Alarm', 'owner_field': 'user_id', 'effect': 'set',
        'new_values': {'enabled': False}, 'proposal_apis': ['phone.update_alarm'],
        'record_argument': 'alarm_id', 'proposal_arguments': {'enabled': False},
        'target_binding': ['target_alarms', 'to_disable_alarm_ids'],
    }], ()),
    763: ([{
        'model': 'venmo.PaymentRequest', 'owner_field': 'receiver_id', 'effect': 'change',
        'fields': ['denied_at'], 'after_not_in': {'denied_at': [None]},
        'proposal_apis': ['venmo.deny_payment_request'], 'record_argument': 'payment_request_id',
    }], ()),
    760: ([PAYMENT_RECEIPT, {
        **PAYMENT_RECEIPT, 'effect': 'add', 'proposal_apis': ['splitwise.record_payment'],
        'proposal_not_in': {'receipt_file_path': [None, '']},
    }], ()),
    263: ([{
        'model': 'venmo.TransactionLike', 'owner_field': 'user_id', 'effect': 'add',
        'owner_via': {'model': 'Transaction', 'owner_field': 'sender_id', 'foreign_key': 'transaction_id'},
        'proposal_apis': ['venmo.like_transaction'],
    }], ()),
    248: ([SPOTIFY_CLOSE], ()),
    249: ([SPOTIFY_CLOSE], ()),
    253: ([AMAZON_WITHDRAWAL], ()),
    310: ([PLAYLIST_RENAME], ()),
    311: ([PLAYLIST_RENAME], ()),
    470: ([PLAYLIST_RENAME], ()),
    471: ([PLAYLIST_RENAME], ()),
    101: ([VENMO_PAY], ()),
    2: ([VENMO_PAY], ()),
    134: ([VENMO_PAY, PHONE_SEND], ()),
    461: ([VENMO_PAY, PHONE_SEND], ()),
    35: ([VENMO_PAY, PHONE_SEND], ()),
    7: (SPOTIFY_REMOVE, ()),
    106: (SPOTIFY_REMOVE, ()),
    125: ([SPOTIFY_PLAY], ()),
    126: ([SPOTIFY_PLAY], ()),
    26: ([SPOTIFY_PLAY], ()),
    27: ([SPOTIFY_PLAY], ()),
    254: ([{
        'model': 'spotify.UserDownloadedSong', 'owner_field': 'user_id', 'effect': 'add',
        'proposal_apis': ['spotify.download_song'],
    }], ()),
    261: ([{
        'model': 'todoist.Task', 'owner_field': 'user_id', 'effect': 'set',
        'new_values': {'is_completed': True}, 'proposal_apis': ['todoist.update_task'],
        'record_argument': 'task_id', 'proposal_arguments': {'is_completed': True},
    }], ()),
}
