from django.forms import Field

from fields import BitcoinAddressValidator


class BitcoinAddressField(Field):

    def __init__(self, *args, **kwargs):
        super(BitcoinAddressField, self).__init__(*args, **kwargs)
        self.validators.append(BitcoinAddressValidator())
