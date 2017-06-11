from django.conf import settings
from django.core.cache import cache

from models import Wallet


def getOrCreateChangeWallet():
    change_wallet, created = Wallet.objects.get_or_create(path=[0], defaults={'change_wallet': True})
    return change_wallet


def getFeeInSatoshisPerByte():
    fee = cache.get('fee_satoshis_per_byte')
    if fee:
        return fee
    return getattr(settings, 'DEFAULT_FEE_SATOSHIS_PER_BYTE', 250)
