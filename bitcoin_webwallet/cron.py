from django.conf import settings
from django.db.models import Sum
from django.utils.timezone import now

from django_cron import CronJobBase, Schedule

import datetime
from decimal import Decimal
from bitcoinrpc.authproxy import AuthServiceProxy

from models import Address, Transaction, OutgoingTransaction, OutgoingTransactionInput, OutgoingTransactionOutput
from utils import getOrCreateChangeWallet


class AddRealBitcoinTransactions(CronJobBase):
    schedule = Schedule(run_every_mins=5, retry_after_failure_mins=5)
    code = 'bitcoin_webwallet.cron.AddRealBitcoinTransactions'

    def do(self):
        rpc = AuthServiceProxy('http://' + settings.BITCOIN_RPC_USERNAME + ':' + settings.BITCOIN_RPC_PASSWORD + '@' + settings.BITCOIN_RPC_IP + ':' + str(settings.BITCOIN_RPC_PORT))

        offset = 0

        while True:
            txs = rpc.listtransactions('', 100, offset)
            offset += 100
            if not txs:
                break
            for tx in txs:
                # If this transaction is already added, then skip it
                if Transaction.objects.filter(incoming_txid=tx['txid']).count():
                    continue

                # Currently only support received
                if tx['category'] != 'receive':
                    continue

                # TODO: What if one Bitcoin transaction is used to send to two of our addresses?
                try:
                    address = Address.objects.get(address=tx['address'])
                except Address.DoesNotExist:
                    continue

                # If address belongs to change wallet, then do not create transaction
                if address.wallet.change_wallet:
                    continue

                new_tx = Transaction.objects.create(
                    wallet=address.wallet,
                    amount=tx['amount'],
                    description='Received',
                    incoming_txid=tx['txid']
                )
                new_tx.created_at = datetime.datetime.fromtimestamp(tx['timereceived'])
                new_tx.save(update_fields=['created_at'])


class SendOutgoingTransactions(CronJobBase):
    schedule = Schedule(run_every_mins=1, retry_after_failure_mins=1)
    code = 'bitcoin_webwallet.cron.SendOutgoingTransactions'

    def do(self):
        rpc = AuthServiceProxy('http://' + settings.BITCOIN_RPC_USERNAME + ':' + settings.BITCOIN_RPC_PASSWORD + '@' + settings.BITCOIN_RPC_IP + ':' + str(settings.BITCOIN_RPC_PORT))

        # Send all outgoing transactions that are ready to go
        otxs_to_send = OutgoingTransaction.objects.filter(inputs_selected_at__isnull=False, sent_at=None)
        for otx in otxs_to_send:
            # Gather inputs argument
            inputs = []
            for inpt in otx.inputs.all():
                inputs.append({
                    'txid': inpt.bitcoin_txid,
                    'vout': inpt.bitcoin_vout,
                })
            # Gather outputs argument
            outputs = {}
            for output in otx.outputs.all():
                outputs.setdefault(output.bitcoin_address, Decimal(0))
                outputs[output.bitcoin_address] += output.amount
            # Use arguments to create, sign and send raw transaction
            raw_tx = rpc.createrawtransaction(inputs, outputs)
            signing_result = rpc.signrawtransaction(raw_tx)
            raw_tx_signed = signing_result['hex']
            if signing_result['complete']:
                rpc.sendrawtransaction(raw_tx_signed)
                otx.sent_at = now()
                otx.save(update_fields=['sent_at'])
                # TODO: Reduce fee from wallets that are part of the sending!

        # Get all outgoing transactions that do not have any inputs selected
        otxs_without_inputs = OutgoingTransaction.objects.filter(inputs_selected_at=None)

        # If all outgoing transactions are fine, then do nothing more
        if otxs_without_inputs.count() == 0:
            return

        # TODO: Some lock here might be a good idea, just to be sure!

        # List all unspent outputs that aren't already assigned to some outgoing transaction
        unspent_outputs_raw = rpc.listunspent(settings.CONFIRMED_THRESHOLD)
        unspent_outputs = []
        for unspent_output in unspent_outputs_raw:
            txid = unspent_output['txid']
            vout = unspent_output['vout']

            if unspent_output['spendable']:

                # If there is no existing input, then this output isn't assigned yet
                if OutgoingTransactionInput.objects.filter(bitcoin_txid=txid, bitcoin_vout=vout).count() == 0:
                    unspent_outputs.append(unspent_output)

        # Assign inputs to those transactions that do not have them set
        for otx in otxs_without_inputs:
            # Calculate how much is being sent
            outputs_total = otx.outputs.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)

            # Calculate fee
            tx_size = 148 * otx.inputs.count() + 34 * (otx.outputs.count() + 1) + 10
            fee = settings.TRANSACTION_FEE_PER_KILOBYTE * ((tx_size + 999) / 1000)

            # Now assign inputs until there is enough for outputs
            inputs_total = otx.inputs.aggregate(Sum('amount'))['amount__sum'] or Decimal(0)
            while inputs_total < outputs_total + fee and len(unspent_outputs) > 0:
                # Find unspent output that has most confirmations
                best_unspent_output = None
                best_unspent_output_i = None
                best_unspent_output_confirmations = 0
                for unspent_outputs_i in range(len(unspent_outputs)):
                    unspent_output = unspent_outputs[unspent_outputs_i]
                    if unspent_output['confirmations'] > best_unspent_output_confirmations:
                        best_unspent_output = unspent_output
                        best_unspent_output_i = unspent_outputs_i
                        best_unspent_output_confirmations = unspent_output['confirmations']

                # Assign this unspent output as input
                OutgoingTransactionInput.objects.create(
                    tx=otx,
                    amount=best_unspent_output['amount'],
                    bitcoin_txid=best_unspent_output['txid'],
                    bitcoin_vout=best_unspent_output['vout'],
                )
                inputs_total += best_unspent_output['amount']

                # Recalculate fee
                tx_size += 148
                fee = settings.TRANSACTION_FEE_PER_KILOBYTE * ((tx_size + 999) / 1000)

                # Remove the best output from unspent outputs
                del unspent_outputs[best_unspent_output_i]

            # If there was no suitable unspent outputs, then it means hot wallet does not
            # have enough funds for this transaction. We have to give up. Already assigned
            # inputs are, however, not cleared. Because of this, we have to give up
            # totally, because this transaction wasted rest of the available outputs.
            if inputs_total < outputs_total + fee:
                break

            # Calculate how much extra there is, and send it back to some of the change
            # addresses. If the system fails right after this operation, it doesn't matter,
            # because the inputs and outputs have perfect match, and next runs will do
            # nothing but set the "inputs_selected_at" timestamp.
            extra_amount = inputs_total - (outputs_total + fee)
            if extra_amount > Decimal(0):
                change_wallet = getOrCreateChangeWallet()
                change_address = change_wallet.getOrCreateAddress(0)
                OutgoingTransactionOutput.objects.create(tx=otx, amount=extra_amount, bitcoin_address=change_address.address)

            # Enough inputs was assigned, so marking this transaction fully assigned
            otx.inputs_selected_at = now()
            otx.save(update_fields=['inputs_selected_at'])
