# -*- coding: utf-8 -*-
from importlib import import_module
from rest_framework.conf import settings
from rest_framework.core.db import models
from rest_framework.core.script import Manager

__author__ = 'caowenbin'

MigrateCommand = Manager(usage="Database related commands")


def get_table_models(module):
    """

    :param module:
    :return:
    """
    table_models = list(
        filter(
            lambda m: isinstance(m, type) and issubclass(m, models.Model)
            and hasattr(m, '_meta') and not getattr(getattr(m, "_meta"), "abstract", False),
            (getattr(module, model) for model in dir(module))
        )
    )

    return table_models


@MigrateCommand.command
def init(*args, **kwargs):
    """
    Initialize the table structure
    """
    installed_apps = settings.INSTALLED_APPS
    for app in installed_apps:
        module = import_module(app)
        table_models = get_table_models(module=module)
        models.create_model_tables(table_models, fail_silently=True)
        table_name_list = [model.__name__ for model in table_models]

        print("Create Table:\n", "\n".join(table_name_list))


@MigrateCommand.command
def clean(*args, **kwargs):
    """
    Clear all table structure
    """
    installed_apps = settings.INSTALLED_APPS
    for app in installed_apps:
        module = import_module(app)
        table_models = get_table_models(module=module)
        models.drop_model_tables(table_models, fail_silently=True)
        table_name_list = [model.__name__ for model in table_models]

        print("Drop Table:\n", "\n".join(table_name_list))
