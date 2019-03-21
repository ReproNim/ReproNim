# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the reproman package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##

import os
from functools import partial
import uuid
import shutil
import tempfile

import pytest

from reproman.cmd import Runner
from reproman.resource.base import ResourceManager
from reproman.tests.skip import skipif
from reproman.utils import chpwd


def get_docker_fixture(image, portmaps={}, name=None,
                       custom_params={}, scope='function',
                       seccomp_unconfined=False):
    """Produce a fixture which starts/stops a docker container

    It should be called to produce and assign within the scope under some name,
    e.g.::

        setup_ssh = get_docker_fixture(
            scope='module',
            image='rastasheep/ubuntu-sshd:14.04',
            portmaps={
                49000: 22
            }
        )

    to create a `setup_ssh` fixture which would start docker image with port
    mapping having a scope of the module (so starts and stops once, not per each
    test within the module)

    Parameters
    ----------
    image: str
      Docker image to run
    portmaps: dict, optional
      Port mappings (host:container)
    name: str, optional
      Container name
    custom_params: whatever, optional
      What to return in a fixture information in the field 'custom'
    scope: {'function', 'class', 'module', 'session'}, optional
      A scope for the fixture according to `pytest.fixture` docs
    seccomp_unconfined : bool, optional
      Disable kernel secure computing mode when creating the container
    """

    @pytest.fixture(scope=scope)
    def docker_fixture():
        """The actual fixture code generated by get_docker_fixture

        on setup, this fixture ensures that a docker container is running
        and starts one if necessary.

        Fixture yields parameters of the container with a `custom` field passed
        into the `get_docker_container`.

        on teardown, this fixture stops the docker container it started
        """
        skipif.no_docker_engine()
        skipif.no_network()
        args = ['docker',
                'run',
                '-d',
                '--rm',
                ]
        if seccomp_unconfined:
            args.extend(['--security-opt', 'seccomp=unconfined'])
        params = {}
        if name:
            args += ['--name', name]
            params['name'] = name

        if portmaps:
            for from_to in portmaps.items():
                args += ['-p', '%d:%d' % from_to]
                params['port'] = from_to[0]
        args += [image]
        stdout, _ = Runner().run(args, expect_stderr=True)
        params['container_id'] = container_id = stdout.strip( )
        params['custom'] = custom_params
        yield params
        Runner().run(['docker', 'stop', container_id])

    return docker_fixture


def get_singularity_fixture(name=None, image="docker://python:2.7",
                            scope="function"):
    """Produce a fixture for a Singularity resource.

    Parameters
    ----------
    name : str or None, optional
        Resource name.  A UUID is generated by default.
    image : str
        Passed to resource.singularity.Singularity.
    scope: {'function', 'class', 'module', 'session'}, optional
        A scope for the fixture according to `pytest.fixture` docs
    """
    @pytest.fixture(scope=scope)
    def fixture():
        skipif.no_network()
        skipif.no_singularity()
        from reproman.resource.singularity import Singularity
        resource = Singularity(name=name or str(uuid.uuid4().hex)[:11],
                               image=image)
        resource.connect()
        list(resource.create())
        yield resource
        resource.delete()
    return fixture


def git_repo_fixture(kind="default", scope="function"):
    """Create a Git repository fixture.

    Parameters
    ----------
    kind : {"empty", "default", "pair"}, optional
        Kind git repository.

        - empty: a repository with no commits.

        - default: a repository with three commits, each adding one of
          its three files: "foo", "bar", and "subdir/baz".

        - pair: a (local, remote) pair of Git repos.  The repos have
          the same structure as the "default" repo, but "local" has a
          remote "origin" with a URL that points to "remote".

    scope : {"function", "class", "module", "session"}, optional
        A `pytest.fixture` scope argument.

    Returns
    -------
    A fixture function.
    """
    runner = Runner()

    def setup_user():
        # Set the user in the local Git configuration rather than
        # through environmental variables so that test functions using
        # this fixture can make commits under the same user.
        runner(["git", "config", "user.name", "A U Thor"])
        runner(["git", "config", "user.email", "a.thor@example.com"])

    def add_and_commit(fname):
        directory = os.path.dirname(fname)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)
        with open(fname, "w") as fh:
            fh.write(fname + "content")
        runner.run(["git", "add", fname])
        runner.run(["git", "commit", "-m", "add " + fname])

    @pytest.fixture(scope=scope)
    def fixture():
        # We can't use pytest's tempdir because that is limited to
        # scope=function.
        tmpdir = tempfile.mkdtemp(prefix="reproman-tests-")
        repodir = os.path.realpath(os.path.join(tmpdir, "repo0"))
        os.mkdir(repodir)

        retval = repodir

        with chpwd(repodir):
            runner.run(["git", "init"])
            setup_user()

            if kind != "empty":
                add_and_commit("foo")
                add_and_commit("bar")
                runner.run(["git", "tag", "tag0"])
                add_and_commit("subdir/baz")

            if kind == "pair":
                localdir = os.path.realpath(os.path.join(tmpdir, "repo1"))
                runner.run(["git", "clone", repodir, localdir],
                           expect_stderr=True)
                with chpwd(localdir):
                    setup_user()
                retval = localdir, repodir
        yield retval
        shutil.rmtree(tmpdir)
    return fixture


def svn_repo_fixture(kind='default', scope='function'):
    """Create a SVN repository fixture.

    Parameters
    ----------
    kind : {"empty", "default"}

        - empty: a repository with no commits.

        - default: a repository with one commit of file "foo".

    scope : {"function", "class", "module", "session"}, optional
        A `pytest.fixture` scope argument.

    Returns
    -------
    A fixture function.
    """
    @pytest.fixture(scope=scope)
    def fixture():
        skipif.no_svn()
        repo_name = 'svnrepo'
        tmpdir = os.path.realpath(tempfile.mkdtemp(prefix='reproman-tests-'))
        root_dir = os.path.join(tmpdir, repo_name)
        subdir = os.path.join(tmpdir, 'subdir')
        os.mkdir(subdir)
        runner = Runner()
        runner.run(['svnadmin', 'create', root_dir])
        runner.run(['svn', 'checkout', 'file://' + root_dir], cwd=subdir)
        checked_out_dir = os.path.join(subdir, repo_name)
        if kind != 'empty':
            runner.run(['touch', 'foo'], cwd=checked_out_dir)
            runner.run(['svn', 'add', 'foo'], cwd=checked_out_dir)
            runner.run(['svn', 'commit', '-m', 'bar'], cwd=checked_out_dir)
        yield (root_dir, checked_out_dir)
        shutil.rmtree(tmpdir)
    return fixture


def job_registry_fixture(scope="function"):
    """Return a fixture for a LocalRegistry object.

    This is like the vanilla LocalRegistry, but points to a temporary
    directory.

    Parameters
    ----------
    scope : {"function", "class", "module", "session"}, optional
        A `pytest.fixture` scope argument.

    Returns
    -------
    A fixture function.
    """
    from reproman.support.jobs.local_registry import LocalRegistry

    @pytest.fixture(scope=scope)
    def fixture(tmpdir_factory):
        return partial(LocalRegistry,
                       str(tmpdir_factory.mktemp("registry")))
    return fixture


def resource_manager_fixture(resources=None, scope="function"):
    """Return a fixture for a ResourceManager instance.

    This points to a temporary inventory and is intended to be used in place of
    the main ResourceManager instance.

    Parameters
    ----------
    resources : dict or None, optional
        Resources to create. Each key is the resource name, and the value
        should be keyword arguments to pass to ResourceManager.create(). If not
        specified, create one shell resource named "myshell".
    scope : {"function", "class", "module", "session"}, optional
        A `pytest.fixture` scope argument.

    Returns
    -------
    A fixture function.
    """
    if resources is None:
        resources = {"myshell": {"resource_type": "shell"}}

    @pytest.fixture(scope=scope)
    def fixture(tmpdir_factory):
        path = str(tmpdir_factory.mktemp("rmanager").join("inventory"))
        manager = ResourceManager(path)
        for name, kwargs in resources.items():
            manager.create(name, **kwargs)
        return manager
    return fixture