from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from bitcoinrpc.authproxy import AuthServiceProxy, JSONRPCException

from pycoin.key import Key

from bitcoin_webwallet.models import Address


class Command(BaseCommand):
    help = 'Makes sure Bitcoin node is aware of all addresses'

    def handle(self, *args, **options):

        rpc = AuthServiceProxy('http://' + settings.BITCOIN_RPC_USERNAME + ':' + settings.BITCOIN_RPC_PASSWORD + '@' + settings.BITCOIN_RPC_IP + ':' + str(settings.BITCOIN_RPC_PORT))

        private_keys_imported = False

        for address in Address.objects.all():
            address_found = True
            try:
                rpc.dumpprivkey(address.address)
            except JSONRPCException as e:
                if e.code == -4:
                    # Address is not found
                    print 'Address ' + address.address + ' was not found. Importing it...'

                    # Do some key magic
                    new_address_full_path = address.wallet.path + [address.subpath_number]
                    new_address_full_path_str = '/'.join([str(i) for i in new_address_full_path])
                    key = Key.from_text(settings.MASTERWALLET_BIP32_KEY)
                    subkey = key.subkeys(new_address_full_path_str).next()

                    # Check address and form the private key
                    btc_address = subkey.address(use_uncompressed=False)
                    assert btc_address == address.address
                    btc_private_key = subkey.wif(use_uncompressed=False)

                    # Do the importing
                    rpc.importprivkey(btc_private_key, '', False)
                    private_keys_imported = True

        if private_keys_imported:
            print 'Note! Private keys were added, but they were not scanned! Please restart bitcoin with -rescan option!'
