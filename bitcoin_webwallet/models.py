from django.conf import settings
from django.db import models, transaction
from django.db.models import Sum

from decimal import Decimal

from pycoin.key import Key

from bitcoinrpc.authproxy import AuthServiceProxy

from jsonfield import JSONField

from fields import BIP32PathField, BitcoinAddressField


class Wallet(models.Model):

    class NotEnoughBalance(Exception):
        pass

    path = BIP32PathField(unique=True)

    # If this wallet is used by this library. These
    # are created automatically, and you should
    # never create wallets where this is set to True.
    internal_wallet = models.BooleanField(default=False)

    def getBalance(self, confirmations):
        current_block_height_queryset = CurrentBlockHeight.objects.order_by('-block_height')
        current_block_height = current_block_height_queryset[0].block_height if current_block_height_queryset.count() else 0
        max_block_height = max(0, current_block_height - confirmations + 1)

        if confirmations > 0:
            txs = self.transactions.exclude(block_height__isnull=True, incoming_txid__isnull=False).exclude(block_height__gt=max_block_height)
        else:
            txs = self.transactions.all()
        return txs.aggregate(Sum('amount')).get('amount__sum') or Decimal(0)

    def getReceived(self, confirmations):
        current_block_height_queryset = CurrentBlockHeight.objects.order_by('-block_height')
        current_block_height = current_block_height_queryset[0].block_height if current_block_height_queryset.count() else 0
        max_block_height = max(0, current_block_height - confirmations + 1)

        if confirmations > 0:
            txs = self.transactions.filter(amount__gt=0).exclude(block_height__isnull=True, incoming_txid__isnull=False).exclude(block_height__gt=max_block_height)
        else:
            txs = self.transactions.all()
        return txs.aggregate(Sum('amount')).get('amount__sum') or Decimal(0)

    def getSent(self):
        txs = self.transactions.filter(amount__lt=0)
        return -(txs.aggregate(Sum('amount')).get('amount__sum') or Decimal(0))

    def getOrCreateAddress(self, subpath_number):
        try:
            return Address.objects.get(wallet=self, subpath_number=subpath_number)
        except Address.DoesNotExist:
            pass

        new_address_full_path = self.path + [subpath_number]
        new_address_full_path_str = '/'.join([str(i) for i in new_address_full_path])

        # Create raw bitcoin address and key
        key = Key.from_text(settings.MASTERWALLET_BIP32_KEY)
        subkey = key.subkeys(new_address_full_path_str).next()

        btc_address = subkey.address(use_uncompressed=False)
        btc_private_key = subkey.wif(use_uncompressed=False)

        # Make sure private key is stored to the database of bitcoind
        rpc = AuthServiceProxy('http://' + settings.BITCOIN_RPC_USERNAME + ':' + settings.BITCOIN_RPC_PASSWORD + '@' + settings.BITCOIN_RPC_IP + ':' + str(settings.BITCOIN_RPC_PORT))
        try:
            rpc.importprivkey(btc_private_key, '', False)
        except:
            raise Exception('Unable to store Bitcoin address to Bitcoin node!')

        # Create new Address and return it
        new_address = Address(wallet=self, subpath_number=subpath_number, address=btc_address)
        new_address.save()

        return new_address

    def getUnusedAddress(self):
        latest_address = self.addresses.order_by('-subpath_number').first()
        if not latest_address:
            return self.getOrCreateAddress(0)
        # If there are on-chain incoming transactions, then return fresh address
        if latest_address.incoming_transactions.filter(incoming_txid__isnull=False).exists():
            return self.getOrCreateAddress(latest_address.subpath_number + 1)
        # No on-chain incoming transaction
        return latest_address

    def sendTo(self, targets_and_amounts, required_confirmations, sender_transaction_description=None):
        # First make sure all amounts are valid. Also sum up the total amount
        total_amount = Decimal(0)
        for target_and_amount in targets_and_amounts:
            amount = target_and_amount[1]
            if not isinstance(amount, Decimal):
                raise Exception('Amount must have Decimal type!')
            if amount.as_tuple().exponent < -8:
                raise Exception('Amount must have a maximum of eight decimal places!')
            if amount <= Decimal(0):
                raise Exception('Amount must be greater than zero!')
            total_amount += amount

        # Start the sending process. This is done atomically,
        # to prevent problems with concurrency
        with transaction.atomic():
            # Make sure this transaction does not make the balance go negative.
            if self.getBalance(required_confirmations) < total_amount:
                raise Wallet.NotEnoughBalance('Not enough balance!')

            tx = Transaction.objects.create(wallet=self, amount=-total_amount, description=sender_transaction_description or '')

            tx_sending_addresses = []

            # This is used if there are other than internal transactions
            outgoing_tx = None

            for target_and_amount in targets_and_amounts:
                target = target_and_amount[0]
                amount = target_and_amount[1]
                transaction_description = target_and_amount[2] if len(target_and_amount) >= 3 else None

                if target is None:
                    raise Exception('Trying to send to None!')

                # Check if target is wallet or address
                target_wallet = None
                target_address = None
                target_internal_address = None
                if isinstance(target, Wallet):
                    target_wallet = target
                    tx_sending_addresses.append({
                        'amount': str(amount)
                    })
                elif isinstance(target, basestring):
                    target_address = target
                    tx_sending_addresses.append({
                        'amount': str(amount),
                        'address': target
                    })

                    # Check if this address belongs to some of the internal wallets
                    try:
                        target_internal_address = Address.objects.get(address=target_address)
                        target_wallet = target_internal_address.wallet
                        target_address = None
                    except Address.DoesNotExist:
                        pass
                else:
                    raise Exception('Invalid target!')

                if target_wallet:

                    # Create new transaction to the receivers wallet
                    Transaction.objects.create(
                        wallet=target_wallet,
                        amount=amount,
                        description=transaction_description or '',
                        receiving_address=target_internal_address
                    )

                elif target_address:

                    # If there is no outgoing transaction, then try
                    # to use some pending outgoing transaction
                    if not outgoing_tx:
                        outgoing_tx = OutgoingTransaction.objects.filter(inputs_selected_at__isnull=True, sent_at__isnull=True).first()
                        # If there was no existing outgoing
                        # transaction, then create a new one.
                        if not outgoing_tx:
                            outgoing_tx = OutgoingTransaction.objects.create()
                        tx.outgoing_tx = outgoing_tx
                        tx.save(update_fields=['outgoing_tx'])

                    # Add new output to outgoing transaction
                    OutgoingTransactionOutput.objects.create(tx=outgoing_tx, amount=amount, bitcoin_address=target_address)

            if tx_sending_addresses:
                tx.sending_addresses = tx_sending_addresses
                tx.save(update_fields=['sending_addresses'])

    def save(self, *args, **kwargs):
        if self.path[0] == 0 and not self.internal_wallet:
            raise Exception('Wallet paths starting with zero are reserved for internal wallets!')
        super(Wallet, self).save(*args, **kwargs)

    def __unicode__(self):
        return '/'.join([str(i) for i in self.path]) + ' balance: ' + ('%.8f' % self.getBalance(0)) + ' BTC'


class Address(models.Model):
    wallet = models.ForeignKey(Wallet, related_name='addresses')

    subpath_number = models.PositiveIntegerField()

    address = BitcoinAddressField()

    def __unicode__(self):
        full_path = self.wallet.path + [self.subpath_number]
        return '/'.join([str(i) for i in full_path]) + ' ' + str(self.address)

    class Meta:
        unique_together = ('wallet', 'subpath_number')


class Transaction(models.Model):
    wallet = models.ForeignKey(Wallet, related_name='transactions')

    created_at = models.DateTimeField(auto_now_add=True)

    amount = models.DecimalField(max_digits=16, decimal_places=8)

    description = models.CharField(max_length=200)

    receiving_address = models.ForeignKey(Address, related_name='incoming_transactions', null=True, blank=True, default=None)
    sending_addresses = JSONField(null=True, blank=True, default=None)

    # Incoming details from real Bitcoin network
    incoming_txid = models.CharField(max_length=64, null=True, blank=True, default=None)
    block_height = models.PositiveIntegerField(null=True, blank=True, default=None)

    # Outgoing details from real Bitcoin network
    outgoing_tx = models.ForeignKey('OutgoingTransaction', related_name='txs', null=True, blank=True, default=None)

    def getConfirmations(self):
        if not self.block_height:
            return 0
        current_block_height_queryset = CurrentBlockHeight.objects.order_by('-block_height')
        current_block_height = current_block_height_queryset[0].block_height if current_block_height_queryset.count() else 0
        return max(0, current_block_height - self.block_height + 1)

    def __unicode__(self):
        if self.amount < Decimal(0):
            result = 'Sent ' + ('%.8f' % -self.amount)
        else:
            result = 'Received ' + ('%.8f' % self.amount)
        result += ' BTC'
        if self.description:
            result += ': ' + self.description
        return result

    class Meta:
        unique_together = ('receiving_address', 'incoming_txid')


class OutgoingTransaction(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    # This means the moment when inputs were agreed
    inputs_selected_at = models.DateTimeField(null=True, blank=True, default=None)

    # This means the moment where transaction was notified as being sent to Bitcoin network
    sent_at = models.DateTimeField(null=True, blank=True, default=None)

    def calculateFee(self):
        outputs_total = self.outputs.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        inputs_total = self.inputs.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        fee = inputs_total - outputs_total
        return fee if fee >= 0 else None

    def __unicode__(self):
        outputs_total = self.outputs.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)

        if not self.inputs_selected_at:
            return u'Sending of {} BTC to {} addresses using {} transactions.'.format(outputs_total, self.outputs.count(), self.txs.count())

        inputs_total = self.inputs.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
        fee = inputs_total - outputs_total

        if not self.sent_at:
            return u'Sending of {} BTC to {} addresses using {} transactions. Fee is {} BTC.'.format(outputs_total, self.outputs.count(), self.txs.count(), fee)

        return u'Sent {} BTC to {} addresses using {} transactions. Fee was {} BTC.'.format(outputs_total, self.outputs.count(), self.txs.count(), fee)


class OutgoingTransactionInput(models.Model):
    tx = models.ForeignKey(OutgoingTransaction, related_name='inputs')

    amount = models.DecimalField(max_digits=16, decimal_places=8)

    bitcoin_txid = models.CharField(max_length=64)
    bitcoin_vout = models.PositiveIntegerField()

    def __unicode__(self):
        return str(self.amount) + ' BTC from ' + self.bitcoin_txid + '/' + str(self.bitcoin_vout)

    class Meta:
        unique_together = ('bitcoin_txid', 'bitcoin_vout')


class OutgoingTransactionOutput(models.Model):
    tx = models.ForeignKey(OutgoingTransaction, related_name='outputs')

    amount = models.DecimalField(max_digits=16, decimal_places=8)

    bitcoin_address = BitcoinAddressField()

    def __unicode__(self):
        return str(self.amount) + ' BTC to ' + str(self.bitcoin_address)


class CurrentBlockHeight(models.Model):
    block_height = models.PositiveIntegerField()
