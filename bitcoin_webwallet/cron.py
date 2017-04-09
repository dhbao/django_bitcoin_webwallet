from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils.timezone import now

from django_cron import CronJobBase, Schedule

import datetime
from decimal import Decimal
from bitcoinrpc.authproxy import AuthServiceProxy
import pytz

from models import Wallet, Address, Transaction, OutgoingTransaction, OutgoingTransactionInput, OutgoingTransactionOutput, CurrentBlockHeight
from utils import getOrCreateChangeWallet


class AddRealBitcoinTransactions(CronJobBase):
    schedule = Schedule(run_every_mins=1, retry_after_failure_mins=1)
    code = 'bitcoin_webwallet.cron.AddRealBitcoinTransactions'

    def do(self):
        rpc = AuthServiceProxy('http://' + settings.BITCOIN_RPC_USERNAME + ':' + settings.BITCOIN_RPC_PASSWORD + '@' + settings.BITCOIN_RPC_IP + ':' + str(settings.BITCOIN_RPC_PORT))

        # Total number of blocks
        blocks = rpc.getblockcount()
        blocks_processed_queryset = CurrentBlockHeight.objects.order_by('-block_height')
        blocks_processed = blocks_processed_queryset[0].block_height if blocks_processed_queryset.count() else 0

        # Now incoming transactions will be processed and added to database. Transactions
        # from new blocks are selected, but also transactions from several older blocks.
        # These extra transactions are updated in case something (for example fork?) is
        # able to modify transactions in old blocks.
        EXTRA_BLOCKS_TO_PROCESS = 6
        process_since = max(0, blocks_processed - EXTRA_BLOCKS_TO_PROCESS)
        process_since_hash = rpc.getblockhash(process_since)

        # Get all old transactions, that require updating
        old_txs = Transaction.objects.filter(incoming_txid__isnull=False, block_height__gt=process_since)
        old_txs = [old_tx for old_tx in old_txs]

        txs = rpc.listsinceblock(process_since_hash)['transactions']
        for tx in txs:
            # Skip other than receiving transactions
            if tx['category'] != 'receive':
                continue

            # Skip unconfirmed transactions for now
            # TODO: Show these too!
            if 'blockhash' not in tx:
                continue

            # Get required info
            txid = tx['txid']
            address = tx['address']
            amount = tx['amount']
            block_height = rpc.getblock(tx['blockhash'])['height']
            created_at = datetime.datetime.utcfromtimestamp(tx['timereceived']).replace(tzinfo=pytz.utc)

            # Skip transaction if it doesn't belong to any Wallet
            try:
                address = Address.objects.get(address=address)
            except Address.DoesNotExist:
                continue

            # Check if transaction already exists
            already_found = False
            for old_tx in old_txs:
                if old_tx.incoming_txid == txid:
                    # Transaction already exists, so do not care about it any more
                    old_txs.remove(old_tx)
                    already_found = True
                    break

            # If transaction is new one
            if not already_found:
                new_tx = Transaction.objects.create(
                    wallet=address.wallet,
                    amount=amount,
                    description='Received',
                    incoming_txid=txid,
                    block_height=block_height,
                    receiving_address=address,
                )
                new_tx.created_at = created_at
                new_tx.save(update_fields=['created_at'])

        # Clean remaining old transactions
        for old_tx in old_txs:
            old_tx.delete()

        # Mark down what the last processed block was
        blocks = rpc.getblockcount()
        if blocks_processed_queryset.exists():
            blocks_processed_queryset.update(block_height=blocks)
        else:
            CurrentBlockHeight.objects.create(block_height=blocks)


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
                # Calculate how much fee each wallet needs to pay
                total_fees = otx.calculateFee()
                fees_for_wallets = []
                if total_fees:
                    txs_count = len(otx.txs.all())
                    for tx in otx.txs.all():
                        wallet_found = False
                        for fee_for_wallet in fees_for_wallets:
                            if fee_for_wallet['wallet'] == tx.wallet:
                                fee_for_wallet['amount'] += total_fees / txs_count
                                wallet_found = True
                        if not wallet_found:
                            fees_for_wallets.append({
                                'wallet': tx.wallet,
                                'amount': total_fees / txs_count,
                            })
                for fee_for_wallet in fees_for_wallets:
                    fee_for_wallet['amount'] = fee_for_wallet['amount'].quantize(Decimal('0.00000001'))

                fee_receiving_wallet = getOrCreateChangeWallet()
                fee_receiving_address = fee_receiving_wallet.getUnusedAddress()

                rpc.sendrawtransaction(raw_tx_signed)

                # Atomically mark outgoing transaction as send and reduce fees from wallets.
                with transaction.atomic():
                    otx.sent_at = now()
                    otx.save(update_fields=['sent_at'])

                    total_effective_fee = Decimal(0)
                    sending_addresses = []
                    for fee_for_wallet in fees_for_wallets:
                        wallet = fee_for_wallet['wallet']
                        amount = fee_for_wallet['amount']
                        # Sending transaction
                        Transaction.objects.create(
                            wallet=wallet,
                            amount=str(-amount),
                            description='Fee from sent Bitcoins',
                            receiving_address=fee_receiving_address,
                        )

                        # Reduce funds
                        wallet = Wallet.objects.get(path=wallet.path)
                        wallet.extra_balance -= amount
                        wallet.save(update_fields=['extra_balance'])

                        # Keep track who sent this
                        sending_addresses.append({
                            'amount': str(amount),
                        })

                        total_effective_fee += amount

                    # Receiving transaction
                    Transaction.objects.create(
                        wallet=fee_receiving_wallet,
                        amount=total_effective_fee,
                        description='Fee refund from sent Bitcoins',
                        sending_addresses=sending_addresses,
                    )

                    # Add funds
                    fee_receiving_wallet = Wallet.objects.get(path=fee_receiving_wallet.path)
                    fee_receiving_wallet.extra_balance += total_effective_fee
                    fee_receiving_wallet.save(update_fields=['extra_balance'])
            elif signing_result.get('errors'):
                raise Exception('Unable to sign outgoing transaction!')

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
            fee = settings.TRANSACTION_FEE_PER_KILOBYTE * Decimal(tx_size) / Decimal(1000)
            fee = fee.quantize(Decimal('0.00000001'))

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
                fee = settings.TRANSACTION_FEE_PER_KILOBYTE * Decimal(tx_size) / Decimal(1000)
                fee = fee.quantize(Decimal('0.00000001'))

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
                change_address = change_wallet.getUnusedAddress()
                OutgoingTransactionOutput.objects.create(tx=otx, amount=extra_amount, bitcoin_address=change_address.address)

            # Enough inputs was assigned, so marking this transaction fully assigned
            otx.inputs_selected_at = now()
            otx.save(update_fields=['inputs_selected_at'])
