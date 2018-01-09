# -*- coding: utf-8 -*-
import copy
from collections import OrderedDict
from rest_framework.conf import settings
from rest_framework.core.exceptions import ValidationError, ErrorDict, ErrorList
from rest_framework.forms.fields import Field, FileField
from rest_framework.utils.cached_property import cached_property

__author__ = 'caowenbin'

__all__ = ['BaseForm', 'Form']


class DeclarativeFieldsMetaclass(type):
    """
    Metaclass that collects Fields declared on the base classes.
    """
    def __new__(mcs, name, bases, attrs):
        current_fields = []
        for key, value in list(attrs.items()):
            if isinstance(value, Field):
                current_fields.append((key, value))
                attrs.pop(key)
        current_fields.sort(key=lambda x: x[1].creation_counter)
        attrs['declared_fields'] = OrderedDict(current_fields)

        new_class = super(DeclarativeFieldsMetaclass, mcs).__new__(mcs, name, bases, attrs)

        # Walk through the MRO.
        declared_fields = OrderedDict()
        for base in reversed(new_class.__mro__):
            # Collect fields from base class.
            if hasattr(base, 'declared_fields') and base.declared_fields:
                declared_fields.update(base.declared_fields)

            # Field shadowing.
            for attr, value in base.__dict__.items():
                if value is None and attr in declared_fields:
                    declared_fields.pop(attr)

        new_class.base_fields = declared_fields
        new_class.declared_fields = declared_fields

        return new_class


class BaseForm(object):

    def __init__(self, request=None, data=None, files=None, initial=None, empty_permitted=False):
        self.request = request
        self.is_bound = data is not None or files is not None
        self.data = data or {}
        self.files = files or {}
        self.initial = initial or {}
        # 是否允许为空提交
        self.empty_permitted = empty_permitted
        self._errors = None
        self._cleaned_data = None
        self._bound_fields_cache = {}
        self._fields = None

    def __iter__(self):
        for name in self.fields:
            yield self[name]

    def __getitem__(self, name):
        """
        Returns a BoundField with the given name
        :param name:
        :return:
        """
        try:
            field = self.fields[name]
        except KeyError:
            raise KeyError(
                "Key '%s' not found in '%s'. Choices are: %s." % (
                    name,
                    self.__class__.__name__,
                    ', '.join(sorted(f for f in self.fields)),
                )
            )
        if name not in self._bound_fields_cache:
            self._bound_fields_cache[name] = field.get_bound_field(self, name)
        return self._bound_fields_cache[name]

    @property
    def fields(self):
        if self._fields is None:
            self._fields = OrderedDict()
            fields = copy.deepcopy(self.base_fields)
            for key, field in fields.items():
                field.bind(field_name=key, parent=self)
                self._fields[key] = field
        return self._fields

    @property
    def cleaned_data(self):
        if self._cleaned_data is None:
            self.full_clean()
        return self._cleaned_data

    @property
    def errors(self):
        """
        Returns an ErrorDict for the data provided for the form
        """
        if self._errors is None:
            self.full_clean()

        return self._errors

    def is_valid(self):
        """
        Returns True if the form has no errors. Otherwise, False. If errors are
        being ignored, returns False.
        """
        return self.is_bound and not self.errors

    def add_error(self, field, error):
        if not isinstance(error, ValidationError):
            error = ValidationError(error)

        if hasattr(error, 'error_dict'):
            if field is not None:
                raise TypeError(
                    "The argument `field` must be `None` when the `error` "
                    "argument contains errors for multiple fields."
                )
            else:
                error = error.error_dict
        else:
            error = {field or settings.NON_FIELD_ERRORS: error.error_list}

        for field, error_list in error.items():
            if field not in self.errors:
                if field != settings.NON_FIELD_ERRORS and field not in self.fields:
                    raise ValueError("'%s' has no field named '%s'." % (self.__class__.__name__, field))
                self._errors[field] = ErrorList()

            self._errors[field].extend(error_list)
            if field in self.cleaned_data:
                del self.cleaned_data[field]

    def has_error(self, field, code=None):
        if code is None:
            return field in self.errors
        if field in self.errors:
            for error in self.errors.as_data()[field]:
                if error.code == code:
                    return True
        return False

    def full_clean(self):
        """
        Cleans all of self.data and populates self._errors and
        self._cleaned_data.
        """
        self._errors = ErrorDict()
        if not self.is_bound:  # Stop further processing.
            return

        self._cleaned_data = {}
        # If the form is permitted to be empty, and none of the form data has
        # changed from the initial data, short circuit any validation.
        if self.empty_permitted and not self.has_changed():
            return
        try:
            self._clean_fields()
            self._clean_form()
            self._clean_validators()
        except ValidationError as e:
            self.add_error(None, e)

    def _clean_fields(self):
        field_errors = {}
        has_error = False
        for name, field in self.fields.items():
            if field.disabled:
                continue
                # value = self.get_initial_for_field(field, name)
            # else:
            value = field.value_from_datadict(self.data, self.files)

            try:
                if isinstance(field, FileField):
                    initial = self.get_initial_for_field(field, name)
                    value = field.clean(value, initial)
                else:
                    value = field.clean(value)

                self._cleaned_data[name] = value

                if hasattr(self, 'clean_%s' % name):
                    value = getattr(self, 'clean_%s' % name)()
                    self._cleaned_data[name] = value
            except ValidationError as e:
                field_errors[name] = e
                has_error = True

        if has_error:
            raise ValidationError(field_errors)

    def _clean_form(self):
        try:
            cleaned_data = self.clean()
        except ValidationError as e:
            self.add_error(None, e)
        else:
            if cleaned_data is not None:
                self._cleaned_data = cleaned_data

    @property
    def validators(self):
        """
        自定义的检查方法
        :return:
        """
        meta = getattr(self, 'Meta', None)
        validators = getattr(meta, 'validators', None)
        return validators[:] if validators is not None else []

    def _clean_validators(self):
        for validator in self.validators:
            if hasattr(validator, 'set_context'):
                validator.set_context(self)

            validator(self.cleaned_data)

    def clean(self):
        """
        Hook for doing any extra form-wide cleaning after Field.clean() has been
        called on every field. Any ValidationError raised by this method will
        not be associated with a particular field; it will have a special-case
        association with the field named '__all__'.
        """
        return self._cleaned_data

    def has_changed(self):
        """
        Returns True if data differs from initial.
        """
        return bool(self.changed_data)

    @cached_property
    def changed_data(self):
        data = []
        for name, field in self.fields.items():
            data_value = field.value_from_datadict(self.data, self.files)
            initial_value = self[name].initial
            if field.has_changed(initial_value, data_value):
                data.append(name)
        return data

    def get_initial_for_field(self, field, field_name):
        """
        Return initial data for field on form. Use initial data from the form
        or the field, in that order. Evaluate callable values.
        """
        value = self.initial.get(field_name, field.default)
        if callable(value):
            value = value()
        return value


class Form(BaseForm, metaclass=DeclarativeFieldsMetaclass):
    pass
