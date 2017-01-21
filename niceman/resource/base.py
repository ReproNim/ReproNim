# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the niceman package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Classes to manage compute resources."""

from importlib import import_module
import abc
import logging

from ..config import ConfigManager
from ..support.exceptions import MissingConfigError, MissingConfigFileError


class ResourceConfig(object):
    """
    Base class for creating and managing resource configuration.
    """

    def __init__(self, resource_config_id, config={}, config_path=None):
        """
        Class constructor

        Parameters
        ----------
        resource_config_id : string
            Configuration identifier as listed in the niceman.cfg file.
            e.g. [resource my-resource-config-id]
        config : dictionary
            Configuration parameters for the resource that will override
            the parameters in the niceman.cfg file
        config_path : string
            Path to niceman.cfg file if overriding the default file locations.
            Default file locations are described in niceman.config.py
        """

        if not config_path and 'config_path' in config:
            config_path = config['config_path']

        if config_path:
            cm = ConfigManager([config_path], False)
        else:
            cm = ConfigManager()
        if len(cm._sections) == 1:
            raise MissingConfigFileError("Unable to locate a niceman.cfg file.")

        # Following statement throws exception, NoSectionError, if section
        # is missing from niceman.cfg file.
        default_config = dict(cm.items('resource ' + resource_config_id))

        # Override niceman.cfg settings with those passed in to the function.
        default_config.update(config)
        self._config = default_config

        # Set some parameters that are nice to have recorded.
        self._config['resource_config_id'] = resource_config_id
        self._config['config_path'] = config_path

        self._lgr = logging.getLogger('niceman.resource_config')

    def __repr__(self):
        return 'ResourceConfig({})'.format(self._config['resource_config_id'])

    def __len__(self):
        return len(self._config)

    def __getitem__(self, item):
        self._lgr.debug('Getting item "{}" in resource config "{}"'. format(item,
            self._config['resource_config_id']))
        return self._config[item]

    def __setitem__(self, key, value):
        self._lgr.debug('Setting item "{}" to "{}" in resource config "{}"'.format(key,
            value, self._config['resource_config_id']))
        self._config[key] = value

    def __delitem__(self, key):
        self._lgr.debug(
            'Deleting item "{}" in resource config "{}"'.format(key,
                self._config['resource_config_id']))
        del self._config[key]

    def __contains__(self, item):
        return item in self._config


class Resource(object):
    """
    Base class for creating and managing compute resources.
    """

    __metaclass__ = abc.ABCMeta

    def __init__(self, resource_config):
        """
        Class constructor

        Parameters
        ----------
        config : ResourceConfig object
            Configuration parameters for the resource.
        """
        self._config = resource_config

        self._lgr = logging.getLogger('niceman.resource')

    def __repr__(self):
        return 'Resource({})'.format(self._config['resource_id'])

    @staticmethod
    def factory(resource_config):
        """
        Factory method for creating the appropriate Container sub-class.

        Parameters
        ----------
        resource_config : ResourceConfig object
            Configuration parameters for the resource.

        Returns
        -------
        Resource sub-class instance.
        """
        if 'resource_type' not in resource_config:
            raise MissingConfigError(
                "Resource 'resource_type' parameter missing for resource.")

        module_name = '_'.join(resource_config['resource_type'].split('-'))
        class_name = ''.join([token.capitalize() for token in resource_config['resource_type'].split('-')])
        module = import_module('niceman.resource.{}'.format(module_name))
        instance = getattr(module, class_name)(resource_config)
        return instance

    @staticmethod
    def get_resource_list(config_path=None):
        """
        Get the resources defined in the niceman.cfg file.

        Parameters
        ----------
        config_path : string
            Path to niceman.cfg file.

        Returns
        -------
        Dictionary containing the settings for all resources. The keys of
        the dictionary are the IDs of the resources.
        """
        if config_path:
            cm = ConfigManager([config_path], False)
        else:
            cm = ConfigManager()

        resources = {}
        for name in cm._sections:
            if name.startswith('resource '):
                resource_id = name.split(' ')[-1]
                resources[resource_id] = cm._sections[name]
                resources[resource_id]['resource_id'] = resource_id
        return resources

    def get_config(self, key):
        """
        Getter access method to the resource configuration dictionary

        Parameters
        ----------
        key : string
            Key ID of configuration parameter

        Returns
        -------
        string : Value of the configuration parameter.
        """
        return self._config[key]

    def set_config(self, key, value):
        """
        Setter access method to the resource configuration dictionary

        Parameters
        ----------
        key : string
            Key ID of configuration parameter
        value : string
            Value of the configuration parameter
        """
        self._config[key] = value

    def has_config(self, key):
        """
        Getter access method to the resource configuration dictionary

        Parameters
        ----------
        key : string
            Key ID of configuration parameter

        Returns
        -------
        boolean : True if key exists in configuration dictionary.
        """
        return key in self._config