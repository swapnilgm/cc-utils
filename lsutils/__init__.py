import git
import github3
import urllib3
urllib3.disable_warnings()
from githubutil import GitHubHelper
import util
from util import info, fail


def create_submodule_update_pull_request(
    repo_path: str,
    repo_branch: str,
    repo_owner_and_name: str,
    submodule_path: str,
    predecessor_repo_owner_and_name: str,
    github_auth_token: str,
    github_url: str='https://github.wdf.sap.corp',
    github_verify_ssl: bool=False,
):
    '''
    Create a pullrequest in the repository on the GitHub-instance which updates the submodule at the given path to
    the commit that is current in the latest release of the predecessor repository.

    Assumes that the submodule is at the same path in both repositories.
    '''
    # get information about submodule in the current repo
    git_repo = git.Repo(repo_path)
    submodule = find_submodule_by_path(git_repo, submodule_path)
    current_submodule_sha = submodule.hexsha

    p_username, p_repository = extract_owner_and_name(predecessor_repo_owner_and_name)
    username, repository = extract_owner_and_name(repo_owner_and_name)

    # get the relevant information about the submodule (i.e. the commit it's pointing to) from the predecessor
    github = github3.github.GitHubEnterprise(
        token=github_auth_token,
        url=github_url,
        verify=github_verify_ssl,
    )

    predecessor_helper = GitHubHelper(github, p_username, p_repository)

    info("Checking newest release for " + p_username + "/" + p_repository + " ...")
    latest_tag = predecessor_helper.get_latest_release_tag_name()
    info("Latest release: " + latest_tag)

    tagged_commit = predecessor_helper.get_tagged_commit_sha(latest_tag)

    # Check submodule at tagged commit
    predecessor_submodule_sha = predecessor_helper.get_submodule_commit_at_sha(submodule_path, tagged_commit)

    if current_submodule_sha != predecessor_submodule_sha:
        info("Found different SHA: " + predecessor_submodule_sha)
    else:
        info("Repository is up-to-date. Skipping upgrade.")
        return

    # Check whether PR already exists. Pull-requests are a github-feature, so we need to create the GitHub
    # representation of the repository as well.
    repo_helper = GitHubHelper(github, username, repository)
    pr_title = get_submodule_pr_title(
            path=submodule_path,
            from_sha=current_submodule_sha,
            to_sha=predecessor_submodule_sha,
        )
    if repo_helper.find_existing_pr(pr_title):
        info("Found existing pull-request for upgrade. Skipping upgrade.")
        return

    # create new branch and checkout
    rnd_string = util.random_str()
    git_repo.create_head(rnd_string).checkout()

    # update submodule commit to the given one
    updated_tree = git_repo.tree(git_repo.head)
    update_submodule(updated_tree, predecessor_submodule_sha, submodule_path)

    git_repo.index.add(updated_tree)
    git_repo.index.commit(message="Update submodule at '{p}' to commit '{s}'".format(
        p=submodule_path,
        s=predecessor_submodule_sha
    ))
    git_repo.remotes.origin.push('{}:{}'.format(rnd_string, rnd_string), force=True)

    info("Creating pull-request for upgrade.")
    repo_helper.create_pull_request(
        title=pr_title,
        base=repo_branch,
        head=rnd_string,
    )


def extract_owner_and_name(owner_and_name: str):
    try:
        username, repository = owner_and_name.split('/')
    except ValueError:
      fail(
          'Could not extract owner- and repository-name from String. Found: {actual}'.format(
              actual=owner_and_name,
          )
      )
    return username, repository

def find_submodule_by_path(repo: git.Repo, path: str):
    for submodule in repo.submodules:
        if submodule.path == path:
            return submodule
    raise ValueError("No submodule found at path '{p}'".format(p=path))

def update_submodule(predecessor_tree, sha, path):
    cache = predecessor_tree.cache
    cache.add(sha, 0o160000, path, force=True)
    cache.set_done()
    return predecessor_tree

def get_submodule_pr_title(path: str, from_sha: str, to_sha: str):
    return '[ci::{path}:{from_sha}->{to_sha}]'.format(
        path=path,
        from_sha=from_sha,
        to_sha=to_sha,
    )
