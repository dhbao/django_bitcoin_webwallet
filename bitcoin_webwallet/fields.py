from django.core.exceptions import ValidationError
from django.db.models import SubfieldBase
from django.db.models.fields import Field
from django.utils.six import with_metaclass
from django.utils.translation import ugettext_lazy as _

from pycoin.key.validate import is_address_valid, is_private_bip32_valid


class BitcoinAddressValidator():
    def __call__(self, value):
        value = str(value)
        if is_address_valid(value) != 'BTC':
            raise ValidationError(_(u'%s is not a valid bitcoin address!') % value)


class BitcoinAddressField(Field):

    description = 'A public bitcoin address'

    def __init__(self, *args, **kwargs):
        super(BitcoinAddressField, self).__init__(*args, **kwargs)
        self.validators.append(BitcoinAddressValidator())

    def db_type(self, connection):
        return 'VARCHAR(35)'

    def to_python(self, value):
        if not value:
            return None
        return value


class BIP32PrivateKeyValidator():
    def __call__(self, value):
        value = str(value)
        if is_private_bip32_valid(value) != 'BTC':
            raise ValidationError(u'%s is not a valid BIP32 private key!' % value)


class BIP32PrivateKeyField(Field):

    description = 'A private BIP32 wallet key'

    def __init__(self, *args, **kwargs):
        super(BIP32PrivateKeyField, self).__init__(*args, **kwargs)
        self.validators.append(BIP32PrivateKeyValidator())

    def db_type(self, connection):
        return 'VARCHAR(112)'

    def to_python(self, value):
        if not value:
            return None
        return value


class BIP32PathField(with_metaclass(SubfieldBase, Field)):

    description = 'Path in BIP32 wallet'

    def __init__(self, *args, **kwargs):
        super(BIP32PathField, self).__init__(*args, **kwargs)

    def db_type(self, connection):
        return 'VARCHAR(255)'

    def to_python(self, value):
        if not value:
            return None
        if isinstance(value, list):
            return value
        return [int(i_str) for i_str in value.split('/')]

    def get_prep_value(self, value):
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValidationError('BIP32Path must be list!')
        for i in value:
            if not isinstance(i, int) and not isinstance(i, long):
                raise ValidationError('BIP32Path must be list of integers or longs!')
            # TODO: Check min and max values!
        return '/'.join([str(i) for i in value])
