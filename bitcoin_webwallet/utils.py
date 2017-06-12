from django.conf import settings
from django.core.cache import cache

from models import Wallet


INTERNAL_WALLET_CHANGE = 0


def get_or_create_internal_wallet(internal_wallet_id):
    return Wallet.objects.get_or_create(path=[0, internal_wallet_id], defaults={'internal_wallet': True})[0]


def get_fee_in_satoshis_per_byte():
    fee = cache.get('fee_satoshis_per_byte')
    if fee:
        return fee
    return getattr(settings, 'DEFAULT_FEE_SATOSHIS_PER_BYTE', 250)
