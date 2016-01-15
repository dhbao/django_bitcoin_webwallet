# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ('bitcoin_webwallet', '0002_auto_20150816_2318'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='sending_addresses',
            field=jsonfield.fields.JSONField(default=None, null=True, blank=True),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='transaction',
            name='receiving_address',
            field=models.ForeignKey(related_name='incoming_transactions', default=None, blank=True, to='bitcoin_webwallet.Address', null=True),
            preserve_default=True,
        ),
    ]
