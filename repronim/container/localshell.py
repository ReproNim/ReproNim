# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the repronim package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Container sub-class to provide management of the localhost environment."""

import os
from repronim.container.base import Container
from repronim.cmd import Runner


class LocalshellContainer(Container):

    def __init__(self, resource, config={}):
        """
        Factory method for creating the appropriate Container sub-class.

        Parameters
        ----------
        resource : object
            Resource sub-class instance
        config : dictionary
            Configuration parameters for the container.

        Returns
        -------
        Container sub-class instance.
        """
        super(LocalshellContainer, self).__init__(resource, config)

    def create(self):
        """
        Create a container instance.
        """

        # Nothing to do to create the localhost "container".
        return

    def execute_command(self, command, env=None):
        """
        Execute the given command in the container.

        Parameters
        ----------
        command : list
            Shell command string or list of command tokens to send to the
            container to execute.
        env : dict
            Additional (or replacement) environment variables which are applied
            only to the current call

        Returns
        -------
        list
            List of STDOUT lines from the container.
        """
        run = Runner()

        command_env = self.get_updated_env(env)

        run_kw = {}
        if command_env:
            # if anything custom, then we need to get original full environment
            # and update it with custom settings which we either "accumulated"
            # via set_envvar, or it was passed into this call.
            run_env = os.environ.copy()
            run_env.update(command_env)
            run_kw['env'] = run_env

        response = run(command, **run_kw)  # , shell=True)
        return [response]