# Generated by Django 2.0.2 on 2018-03-08 18:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ega', '0002_auto_20180218_1324'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='pk_away_goals',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='match',
            name='pk_home_goals',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='prediction',
            name='penalties',
            field=models.CharField(blank=True, max_length=1),
        ),
    ]