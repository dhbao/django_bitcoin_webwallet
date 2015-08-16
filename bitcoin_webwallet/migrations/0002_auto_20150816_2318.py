# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('bitcoin_webwallet', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CurrentBlockHeight',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('block_height', models.PositiveIntegerField()),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.AddField(
            model_name='transaction',
            name='block_height',
            field=models.PositiveIntegerField(default=None, null=True, blank=True),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='transaction',
            name='receiving_address',
            field=models.ForeignKey(related_name='transactions', default=None, blank=True, to='bitcoin_webwallet.Address', null=True),
            preserve_default=True,
        ),
    ]
