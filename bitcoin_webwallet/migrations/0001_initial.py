# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import bitcoin_webwallet.fields


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Address',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('subpath_number', models.PositiveIntegerField()),
                ('address', bitcoin_webwallet.fields.BitcoinAddressField()),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='OutgoingTransaction',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('inputs_selected_at', models.DateTimeField(default=None, null=True, blank=True)),
                ('sent_at', models.DateTimeField(default=None, null=True, blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='OutgoingTransactionInput',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('amount', models.DecimalField(max_digits=16, decimal_places=8)),
                ('bitcoin_txid', models.CharField(max_length=64)),
                ('bitcoin_vout', models.PositiveIntegerField()),
                ('tx', models.ForeignKey(related_name='inputs', to='bitcoin_webwallet.OutgoingTransaction')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='OutgoingTransactionOutput',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('amount', models.DecimalField(max_digits=16, decimal_places=8)),
                ('bitcoin_address', bitcoin_webwallet.fields.BitcoinAddressField()),
                ('tx', models.ForeignKey(related_name='outputs', to='bitcoin_webwallet.OutgoingTransaction')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('amount', models.DecimalField(max_digits=16, decimal_places=8)),
                ('description', models.CharField(max_length=200)),
                ('incoming_txid', models.CharField(default=None, max_length=64, unique=True, null=True, blank=True)),
                ('outgoing_tx', models.ForeignKey(related_name='txs', default=None, blank=True, to='bitcoin_webwallet.OutgoingTransaction', null=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Wallet',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('path', bitcoin_webwallet.fields.BIP32PathField(unique=True)),
                ('extra_balance', models.DecimalField(default=0, max_digits=16, decimal_places=8)),
                ('change_wallet', models.BooleanField(default=False)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='transaction',
            name='wallet',
            field=models.ForeignKey(related_name='transactions', to='bitcoin_webwallet.Wallet'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='outgoingtransactioninput',
            unique_together=set([('bitcoin_txid', 'bitcoin_vout')]),
        ),
        migrations.AddField(
            model_name='address',
            name='wallet',
            field=models.ForeignKey(related_name='addresses', to='bitcoin_webwallet.Wallet'),
            preserve_default=True,
        ),
        migrations.AlterUniqueTogether(
            name='address',
            unique_together=set([('wallet', 'subpath_number')]),
        ),
    ]
