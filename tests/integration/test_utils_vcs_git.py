from __future__ import annotations

import uuid

from copy import deepcopy
from hashlib import sha1
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from dulwich.client import HTTPUnauthorized
from dulwich.client import get_transport_and_path
from dulwich.repo import Repo
from poetry.core.pyproject.toml import PyProjectTOML

from poetry.console.exceptions import PoetrySimpleConsoleException
from poetry.vcs.git import Git
from poetry.vcs.git.backend import GitRefSpec


if TYPE_CHECKING:
    from _pytest.tmpdir import TempdirFactory
    from dulwich.client import FetchPackResult
    from dulwich.client import GitClient
    from pytest_mock import MockerFixture

    from tests.conftest import Config


# these tests are integration as they rely on an external repository
# see `source_url` fixture
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def git_mock() -> None:
    pass


@pytest.fixture(autouse=True)
def setup(config: Config) -> None:
    pass


REVISION_TO_VERSION_MAP = {
    "b6204750a763268e941cec1f05f8986b6c66913e": "0.1.0",  # Annotated Tag
    "18d3ff247d288da701fc7f9ce2ec718388fca266": "0.1.1-alpha.0",
    "dd07e8d4efb82690e7975b289917a7782fbef29b": "0.2.0-alpha.0",
    "7263819922b4cd008afbb447f425a562432dad7d": "0.2.0-alpha.1",
}

BRANCH_TO_REVISION_MAP = {"0.1": "18d3ff247d288da701fc7f9ce2ec718388fca266"}

TAG_TO_REVISION_MAP = {"v0.1.0": "b6204750a763268e941cec1f05f8986b6c66913e"}

REF_TO_REVISION_MAP = {
    "branch": BRANCH_TO_REVISION_MAP,
    "tag": TAG_TO_REVISION_MAP,
}


@pytest.fixture
def use_system_git_client(config: Config) -> None:
    config.merge({"experimental": {"system-git-client": True}})


@pytest.fixture(scope="module")
def source_url() -> str:
    return "https://github.com/python-poetry/test-fixture-vcs-repository.git"


@pytest.fixture(scope="module")
def source_directory_name(source_url: str) -> str:
    return Git.get_name_from_source_url(url=source_url)


@pytest.fixture(scope="module")
def local_repo(tmpdir_factory: TempdirFactory, source_directory_name: str) -> Repo:
    with Repo.init(
        tmpdir_factory.mktemp("src") / source_directory_name, mkdir=True
    ) as repo:
        yield repo


@pytest.fixture(scope="module")
def _remote_refs(source_url: str, local_repo: Repo) -> FetchPackResult:
    client: GitClient
    path: str
    client, path = get_transport_and_path(source_url)
    return client.fetch(
        path, local_repo, determine_wants=local_repo.object_store.determine_wants_all
    )


@pytest.fixture
def remote_refs(_remote_refs: FetchPackResult) -> FetchPackResult:
    return deepcopy(_remote_refs)


@pytest.fixture(scope="module")
def remote_default_ref(_remote_refs: FetchPackResult) -> bytes:
    return _remote_refs.symrefs[b"HEAD"]


@pytest.fixture(scope="module")
def remote_default_branch(remote_default_ref: bytes) -> str:
    return remote_default_ref.decode("utf-8").replace("refs/heads/", "")


def test_git_clone_default_branch_head(
    source_url: str,
    remote_refs: FetchPackResult,
    remote_default_ref: bytes,
    mocker: MockerFixture,
):
    spy = mocker.spy(Git, "_clone")
    spy_legacy = mocker.spy(Git, "_clone_legacy")

    with Git.clone(url=source_url) as repo:
        assert remote_refs.refs[remote_default_ref] == repo.head()

    spy_legacy.assert_not_called()
    spy.assert_called()


def test_git_clone_fails_for_non_existent_branch(source_url: str):
    branch = uuid.uuid4().hex

    with pytest.raises(PoetrySimpleConsoleException) as e:
        Git.clone(url=source_url, branch=branch)

    assert f"Failed to clone {source_url} at '{branch}'" in str(e.value)


def test_git_clone_fails_for_non_existent_revision(source_url: str):
    revision = sha1(uuid.uuid4().bytes).hexdigest()

    with pytest.raises(PoetrySimpleConsoleException) as e:
        Git.clone(url=source_url, revision=revision)

    assert f"Failed to clone {source_url} at '{revision}'" in str(e.value)


def assert_version(repo: Repo, expected_revision: str) -> None:
    version = PyProjectTOML(
        path=Path(repo.path).joinpath("pyproject.toml")
    ).poetry_config["version"]

    revision = Git.get_revision(repo=repo)

    assert revision == expected_revision
    assert revision in REVISION_TO_VERSION_MAP
    assert version == REVISION_TO_VERSION_MAP[revision]


def test_git_clone_when_branch_is_ref(source_url: str) -> None:
    with Git.clone(url=source_url, branch="refs/heads/0.1") as repo:
        assert_version(repo, BRANCH_TO_REVISION_MAP["0.1"])


@pytest.mark.parametrize("branch", [*BRANCH_TO_REVISION_MAP.keys()])
def test_git_clone_branch(
    source_url: str, remote_refs: FetchPackResult, branch: str
) -> None:
    with Git.clone(url=source_url, branch=branch) as repo:
        assert_version(repo, BRANCH_TO_REVISION_MAP[branch])


@pytest.mark.parametrize("tag", [*TAG_TO_REVISION_MAP.keys()])
def test_git_clone_tag(source_url: str, remote_refs: FetchPackResult, tag: str) -> None:
    with Git.clone(url=source_url, tag=tag) as repo:
        assert_version(repo, TAG_TO_REVISION_MAP[tag])


def test_git_clone_multiple_times(
    source_url: str, remote_refs: FetchPackResult
) -> None:
    for revision in REVISION_TO_VERSION_MAP:
        with Git.clone(url=source_url, revision=revision) as repo:
            assert_version(repo, revision)


def test_git_clone_revision_is_branch(
    source_url: str, remote_refs: FetchPackResult
) -> None:
    with Git.clone(url=source_url, revision="0.1") as repo:
        assert_version(repo, BRANCH_TO_REVISION_MAP["0.1"])


def test_git_clone_revision_is_ref(
    source_url: str, remote_refs: FetchPackResult
) -> None:
    with Git.clone(url=source_url, revision="refs/heads/0.1") as repo:
        assert_version(repo, BRANCH_TO_REVISION_MAP["0.1"])


@pytest.mark.parametrize(
    ("revision", "expected_revision"),
    [
        ("0.1", BRANCH_TO_REVISION_MAP["0.1"]),
        ("v0.1.0", TAG_TO_REVISION_MAP["v0.1.0"]),
        *zip(REVISION_TO_VERSION_MAP, REVISION_TO_VERSION_MAP),
    ],
)
def test_git_clone_revision_is_tag(
    source_url: str, remote_refs: FetchPackResult, revision: str, expected_revision: str
) -> None:
    with Git.clone(url=source_url, revision=revision) as repo:
        assert_version(repo, expected_revision)


def test_git_clone_clones_submodules(source_url: str) -> None:
    with Git.clone(url=source_url) as repo:
        submodule_package_directory = (
            Path(repo.path) / "submodules" / "sample-namespace-packages"
        )

    assert submodule_package_directory.exists()
    assert submodule_package_directory.joinpath("README.md").exists()
    assert len(list(submodule_package_directory.glob("*"))) > 1


def test_system_git_fallback_on_http_401(
    mocker: MockerFixture,
    source_url: str,
) -> None:
    spy = mocker.spy(Git, "_clone_legacy")
    mocker.patch.object(Git, "_clone", side_effect=HTTPUnauthorized(None, None))

    with Git.clone(url=source_url, branch="0.1") as repo:
        path = Path(repo.path)
        assert_version(repo, BRANCH_TO_REVISION_MAP["0.1"])

    spy.assert_called_with(
        url="https://github.com/python-poetry/test-fixture-vcs-repository.git",
        target=path,
        refspec=GitRefSpec(branch="0.1", revision=None, tag=None, ref=b"HEAD"),
    )
    spy.assert_called_once()


def test_system_git_called_when_configured(
    mocker: MockerFixture, source_url: str, use_system_git_client: None
) -> None:
    spy_legacy = mocker.spy(Git, "_clone_legacy")
    spy = mocker.spy(Git, "_clone")

    with Git.clone(url=source_url, branch="0.1") as repo:
        path = Path(repo.path)
        assert_version(repo, BRANCH_TO_REVISION_MAP["0.1"])

    spy.assert_not_called()

    spy_legacy.assert_called_once()
    spy_legacy.assert_called_with(
        url=source_url,
        target=path,
        refspec=GitRefSpec(branch="0.1", revision=None, tag=None, ref=b"HEAD"),
    )
