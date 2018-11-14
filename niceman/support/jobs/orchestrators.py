# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil; coding: utf-8 -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the niceman package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Orchestrators for `niceman run`.
"""

import abc
import collections
import logging
import os
import os.path as op
import uuid
from tempfile import NamedTemporaryFile
import time

import jinja2
import six
from six.moves import shlex_quote

from niceman.dochelpers import borrowdoc
from niceman.support.jobs.submitters import SUBMITTERS
from niceman.support.exceptions import MissingExternalDependency
from niceman.support.external_versions import external_versions

lgr = logging.getLogger("niceman.support.jobs.orchestrators")


@six.add_metaclass(abc.ABCMeta)
class Orchestrator(object):
    """Base Orchestrator class.

    An Orchestrator is responsible for preparing a directory to run a command,
    submitting it with the specified submitter, and then handling the results.
    """

    def __init__(self, resource, submission_type, job_spec=None):
        self.resource = resource
        self.session = resource.get_session()

        # TODO: Probe remote and try to infer.
        submitter_class = SUBMITTERS[submission_type or "local"]
        self.submitter = submitter_class(self.session)

        self.job_spec = job_spec or {}
        self.jobid = "{}-{}".format(time.strftime("%Y%m%d-%H%M%S"),
                                    str(uuid.uuid4())[:4])
        self.submission_id = None

        self._working_directory = None
        self._root_directory = None

    @property
    def root_directory(self):
        """The root run directory on the resource.

        The working directory for a particular command is a subdirectory of
        this directory.
        """
        # TODO: We should allow root directory to be configured for each
        # resource.  What's the best way to do this?  Adding an attr for each
        # resource class is a lot of duplication.
        if self._root_directory is not None:
            return self._root_directory

        root_directory = self.job_spec.pop("root_directory", None)
        if not root_directory:
            remote_pwd, _ = self.session.execute_command("printf '%s' $PWD")
            if not remote_pwd:
                raise ValueError("Could not determine PWD on remote")
            root_directory = op.join(
                remote_pwd, ".niceman",
                # We won't require these to be DataLad datasets... better name?
                "datasets")
            lgr.info("No root directory supplied for %s; using '%s'",
                     self.resource.name, root_directory)
        if not op.isabs(root_directory):
            raise ValueError("Root directory is not an absolute path: {}"
                             .format(root_directory))
        self._root_directory = root_directory
        return root_directory

    @abc.abstractproperty
    def working_directory(self):
        """Directory in which to run the command.
        """
        pass

    @property
    def meta_directory(self):
        """Directory used to store metadata for the run.
        """
        return op.join(self.working_directory, ".niceman", "jobs",
                       self.resource.name, self.jobid)

    def prepare_remote(self, inputs):
        """Prepare remote for run.

        Parameters
        ----------
        inputs : list of str
            Input files for the command.
        """
        if not self.session.exists(self.root_directory):
            self.session.mkdir(self.root_directory, parents=True)

    def _render_template(self, template_name, subdir):
        lgr.debug("Using template %s", template_name)
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(
                [op.join(op.dirname(__file__), "job_templates", subdir)]),
            undefined=jinja2.StrictUndefined,
            trim_blocks=True)
        env.globals["shlex_quote"] = shlex_quote
        template = env.get_template(template_name)

        return template.render(
            jobid=self.jobid,
            root_directory=self.root_directory,
            remote_directory=self.working_directory,
            meta_directory=self.meta_directory,
            **self.job_spec or {})

    def render_runscript(self, template_name=None):
        """Generate the run script from `template_name`.

        A run script is a wrapper around the original command and may do
        additional pre- and post-processing.

        Parameters
        ----------
        template_name : str, optional
            Name of template to use instead of the default one for this class.

        Returns
        -------
        Rendered run script (str).
        """
        return self._render_template(
            template_name or "{}.template.sh".format(self.name),
            "runscript")

    def render_submission(self, template_name=None):
        """Generate the submission file from `template_name`.

        A submission file is the file the will be passed to `submitter.submit`.
        It should result in the execution of the run script.

        Parameters
        ----------
        template_name : str, optional
            Name of template to use instead of the default one for this class.

        Returns
        -------
        Rendered submission file (str).
        """
        return self._render_template(
            template_name or "{}.template".format(self.submitter.name),
            "submission")

    def submit(self):
        """Submit the job with `submitter`.
        """
        session = self.session

        remote_script = op.join(self.meta_directory, "runscript")
        with NamedTemporaryFile('w', prefix="niceman-", delete=False) as tfh:
            tfh.write(self.render_runscript())
        os.chmod(tfh.name, 0o755)
        session.put(tfh.name, remote_script)
        os.unlink(tfh.name)

        submission_file = op.join(self.meta_directory, "submit")
        with NamedTemporaryFile('w', prefix="niceman-", delete=False) as tfh:
            tfh.write(self.render_submission())
        os.chmod(tfh.name, 0o755)
        session.put(tfh.name, submission_file)
        os.unlink(tfh.name)

        subm_id = self.submitter.submit(submission_file)
        if subm_id is None:
            lgr.warning("No submission ID obtained for %s", self.jobid)
        else:
            lgr.debug("Job %s submitted", subm_id)
            session.execute_command("echo {} >{}".format(
                subm_id,
                op.join(self.meta_directory, "idmap")))

    @abc.abstractmethod
    def follow(self, outputs):
        """Follow the submission.

        Parameters
        ----------
        outputs : list of str
            Pre-specified outputs of the submitted command.
        """
        pass


# TODO: Need to rework/polish/extend the orchestrators. Think about how to
# handle the orchestration type (plain, datalad local, datalad pair, ...),
# shared/non-shared file system, and batch system interaction at both the class
# and template level.

# TODO: Improve the docstring descriptions of what the orchestrators do.


class DataladPairOrchestrator(Orchestrator):
    """Execute command with remote dataset sibling to execute command.
    """

    name = "datalad-pair"

    def __init__(self, resource, submitter, job_spec=None):
        if not external_versions["datalad"]:
            raise MissingExternalDependency(
                "DataLad is required for orchestrator '{}'".format(self.name))

        super(DataladPairOrchestrator, self).__init__(
            resource, submitter, job_spec)

        from datalad.api import Dataset
        self.ds = Dataset(".")
        if not self.ds.id:
            raise ValueError("datalad-pair requires a local dataset")

    @property
    @borrowdoc(Orchestrator)
    def working_directory(self):
        return self._working_directory or op.join(self.root_directory,
                                                  self.ds.id)

    @borrowdoc(Orchestrator)
    def prepare_remote(self, inputs):
        super(DataladPairOrchestrator, self).prepare_remote(inputs)
        resource = self.resource
        session = self.session

        # Stick to git scp-like syntax for now since something like
        #
        #   shurl = "ssh://{}@{}:{}{}".format(
        #       resource.user, resource.host, resource.port, remote_dir)
        #
        # can fail with
        #
        #   stderr: 'fatal: ssh variant 'simple' does not support setting port'
        #   [cmd.py:wait:415] (GitCommandError)
        #
        # depending on the setting of ssh.variant.  For non-standard ports,
        # this relies on the user setting up their ssh config.

        # TODO: Check that we're on the right commit.

        if resource.type == "ssh":
            sshurl = "{}{}:{}".format(
                resource.user + "@" if resource.user else "",
                resource.host,
                self.working_directory)

            if resource.port:
                lgr.warning("Using SSH url %s; "
                            "port should be specified in SSH config",
                            sshurl)

            # TODO: Add one level deeper with reckless clone per job to deal
            # with concurrent jobs?
            if not session.exists(self.working_directory):
                self.ds.create_sibling(sshurl, name=resource.name,
                                       recursive=True)

            # Should use --since for existing repo, but it doesn't seem to sync
            # wrt content.
            self.ds.publish(to=resource.name, path=inputs, recursive=True)
        elif resource.type == "shell":
            import datalad.api as dl
            if not session.exists(self.working_directory):
                dl.install(self.working_directory, source=self.ds.path)
            if inputs:
                installed_ds = dl.Dataset(self.working_directory)
                installed_ds.get(inputs)
        else:
            # TODO: Handle more types?
            # TODO: Raise a more specific error.
            raise ValueError("Unsupported resource type {}"
                             .format(resource.type))
        if not session.exists(self.meta_directory):
            session.mkdir(self.meta_directory, parents=True)

    @borrowdoc(Orchestrator)
    def follow(self, outputs):
        self.submitter.follow()
        if self.resource.type == "ssh":
            self.ds.update(sibling=self.resource.name,
                           merge=True, recursive=True)
            if outputs:
                self.ds.get(path=outputs)
        elif self.resource.type == "shell":
            # Below is just for local testing.  It doesn't support actually
            # getting the content.
            self.session.execute_command(
                ["git", "fetch", self.working_directory,
                 "refs/heads/master:refs/niceman/{}".format(self.jobid)])
            self.session.execute_command(
                ["git", "merge", "FETCH_HEAD"])


class DataladRunOrchestrator(DataladPairOrchestrator):
    """Capture results locally as run record.
    """
    # TODO: This should be restructured so that the remote end isn't required
    # to have datalad.

    name = "datalad-run"

    def __init__(self, resource, submitter, job_spec=None):
        super(DataladRunOrchestrator, self).__init__(
            resource, submitter, job_spec)
        self.run_kwds = {}

    @borrowdoc(DataladPairOrchestrator)
    def prepare_remote(self, inputs):
        super(DataladRunOrchestrator, self).prepare_remote(inputs)
        self.run_kwds["inputs"] = inputs

    @borrowdoc(DataladPairOrchestrator)
    def follow(self, outputs):
        self.submitter.follow()

        if self.resource.type == "ssh":
            self.ds.repo.fetch(
                remote=self.resource.name,
                refspec="refs/niceman/*:refs/niceman/*")
        else:  # For local testing.
            self.session.execute_command(
                ["git", "fetch", self.working_directory,
                 "refs/niceman/*:refs/niceman/*"])

        import tarfile
        tfile = "{}.tar.gz".format(self.jobid)
        remote_tfile = op.join(self.root_directory, "outputs", tfile)

        if not self.session.exists(remote_tfile):
            lgr.error("Expected output file %s does not exist", remote_tfile)
            return

        self.session.get(op.join(self.root_directory, "outputs", tfile))
        with tarfile.open(tfile, mode="r:gz") as tar:
            tar.extractall(path=".")
        os.unlink(tfile)

        from datalad.interface.run import run_command
        lgr.info("Creating run commit")
        for res in run_command(outputs=outputs,
                               inject=True,
                               extra_info={"niceman_jobid": self.jobid},
                               cmd=self.job_spec["command_str"],
                               **self.run_kwds):
            # Oh, if only I were a datalad extension.
            pass


ORCHESTRATORS = collections.OrderedDict(
    (o.name, o) for o in [
        DataladPairOrchestrator,
        DataladRunOrchestrator,
    ]
)
