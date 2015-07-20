from models import Wallet


def getOrCreateChangeWallet():
    change_wallet, created = Wallet.objects.get_or_create(path=[0], defaults={'change_wallet': True})
    return change_wallet
