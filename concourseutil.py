# Copyright 2018 The Gardener Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import subprocess

from copy import copy
from ensure import ensure_annotations
from github3.github import GitHubEnterprise, GitHub
from urllib.parse import urlparse

from util import parse_yaml_file, info, fail, which, warning, CliHints, CliHint
from util import ctx as global_ctx
from concourse import pipelines
import concourse.client as concourse
import concourse.setup as setup
from model import ConfigFactory, ConcourseTeamCredentials
import kubeutil
from kubeutil import KubernetesNamespaceHelper
import github
from githubutil import _create_github_api_object


def __add_module_command_args(parser):
    parser.add_argument('--kubeconfig', required=False)
    return parser


def deploy_or_upgrade_concourse(
    config_dir: CliHints.existing_dir("Directory containing Concourse configuration (e.g.: A checked-out kubernetes/cc-config repository)."),
    config_name: CliHint(typehint=str, help="Which of the configurations contained in --config-dir to use."),
    deployment_name: CliHint(typehint=str, help="Name under which Concourse will be deployed. Will also be the identifier of the namespace into which it is deployed.")='concourse',
    dry_run: bool=True,
    ):
    '''Deploys a new concourse-instance using the given deployment name and config-directory.'''
    which("helm")

    config_dir = os.path.abspath(config_dir)
    namespace = deployment_name
    _display_info(
        dry_run=dry_run,
        operation="DEPLOYED",
        deployment_name=deployment_name,
        config_dir=config_dir
    )

    if dry_run:
        return

    setup.deploy_or_upgrade_concourse(
        config_dir=config_dir,
        config_name=config_name,
        deployment_name=deployment_name,
    )


def destroy_concourse(release: str, dry_run: bool = True):
    _display_info(
        dry_run=dry_run,
        operation="DESTROYED",
        deployment_name=release,
    )

    if dry_run:
        return

    helm_executable = which("helm")
    context = kubeutil.Ctx()
    namespace_helper = KubernetesNamespaceHelper(context.create_core_api())
    namespace_helper.delete_namespace(namespace=release)
    helm_env = os.environ.copy()

    # Check for optional arg --kubeconfig
    cli_args = global_ctx().args
    if cli_args and hasattr(cli_args, 'kubeconfig') and cli_args.kubeconfig:
        helm_env['KUBECONFIG'] = cli_args.kubeconfig

    subprocess.run([helm_executable, "delete", release, "--purge"], env=helm_env)


def set_teams(
    config_dir: CliHints.existing_dir('Path to a directory containing Concourse-configuration (e.g. cc-config)'),
    config_name: CliHint(typehint=str, help='Which of the configurations contained in "--config-file" to use.'),
    config_file: CliHint(typehint=str, help='File inside "--config-dir" containing the configurations.')="configs.yaml",
    ):
    factory = ConfigFactory.from_cfg_dir(cfg_dir=config_dir)
    config_set = factory.cfg_set(cfg_name=config_name)
    config = config_set.concourse()
    main_team_credentials = config.team_credentials("main")
    concourse_api = concourse.ConcourseApi(
        base_url=config.external_url(),
        team_name=main_team_credentials.teamname(),
    )
    concourse_api.login(
        team=main_team_credentials.teamname(),
        username=main_team_credentials.username(),
        passwd=main_team_credentials.passwd(),
    )
    for team in config.all_team_credentials():
        # We skip the main team here since we cannot update all its credentials at this time.
        if team.teamname == "main":
            continue
        concourse_api.set_team(team)


def _display_info(dry_run: bool, operation: str, **kwargs):
    info("Concourse will be {o} using helm with the following arguments".format(o=operation))
    max_leng = max(map(len, kwargs.keys()))
    for k, v in kwargs.items():
        key_str = k.ljust(max_leng)
        info("{k}: {v}".format(k=key_str, v=v))

    if dry_run:
        warning("this was a --dry-run. Set the --no-dry-run flag to actually deploy")


def render_secrets(cfg_dir: CliHints.existing_dir(), cfg_name: str, out_file: str, external_url: str = None):
    fail('currrently no longer implemented')
    # todo: serialise configuration set or rm function


def render_pipeline(
        pipeline_definition_file: str,
        config_dir: str,
        config_name: str,
        template_path: [str],
        template_include_dir: str
    ):
    pipeline_definition = parse_yaml_file(pipeline_definition_file)
    template_path = template_path

    cfg_factory = ConfigFactory.from_cfg_dir(cfg_dir=config_dir)
    config_set = cfg_factory.cfg_set(cfg_name=config_name)

    for pipeline_str, _, _ in pipelines.render_pipelines(
            pipeline_definition,
            config_set,
            template_path,
            template_include_dir
        ):
        print(pipeline_str)


def render_pipelines(
        definition_directories: [str],
        template_path: [str],
        config_dir: str,
        config_name: str,
        template_include_dir: str,
        out_dir: str
    ):
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)

    cfg_factory = ConfigFactory.from_cfg_dir(cfg_dir=config_dir)
    config_set = cfg_factory.cfg_set(cfg_name=config_name)

    for rendered_pipeline, definition, pipeline_args in pipelines.generate_pipelines(
            definition_directories=definition_directories,
            template_path=template_path,
            template_include_dir=template_include_dir,
            config_set=config_set
        ):
        out_name = os.path.join(out_dir, pipeline_args.name + '.yaml')
        with open(out_name, 'w') as f:
            f.write(rendered_pipeline)


def deploy_pipeline(
        pipeline_file: CliHint('generated pipeline definition to deploy'),
        pipeline_name: CliHint('the name under which the pipeline shall be deployed'),
        team_name: CliHint('name of the target team'),
        config_dir: CliHints.existing_dir('directory containing Concourse configuration'),
        config_name: CliHints.existing_file('identifier of the configuration in the config directory to use')
):
    cfg_factory = ConfigFactory.from_cfg_dir(cfg_dir=config_dir)
    concourse_cfg = cfg_factory.concourse(config_name)
    team_credentials = concourse_cfg.team_credentials(team_name)

    with open(pipeline_file) as f:
        pipeline_definition = f.read()

    pipelines.deploy_pipeline(
        pipeline_definition=pipeline_definition,
        pipeline_name=pipeline_name,
        concourse_cfg=concourse_cfg,
        team_credentials=team_credentials,
    )


def _list_github_resources(
  concourse_url:str,
  concourse_user:str='kubernetes',
  concourse_passwd:str='kubernetes',
  concourse_team:str='kubernetes',
  concourse_pipelines=None,
  github_url:str=None,
):
    concourse_api = concourse.ConcourseApi(base_url=concourse_url, team_name=concourse_team)
    concourse_api.login(
      team=concourse_team,
      username=concourse_user,
      passwd=concourse_passwd
    )
    github_hostname = urlparse(github_url).netloc
    pipeline_names = concourse_pipelines if concourse_pipelines else concourse_api.pipelines()
    for pipeline_name in pipeline_names:
        pipeline_cfg = concourse_api.pipeline_cfg(pipeline_name)
        resources = pipeline_cfg.resources
        resources = filter(lambda r: r.has_webhook_token(), resources)
        # only process repositories from concourse's "default" github repository
        resources = filter(lambda r: r.github_source().hostname() == github_hostname, resources)

        for resource in resources:
            yield resource


def sync_webhooks(
  github_auth_token:str,
  github_url:str,
  github_verify_ssl:bool=False,
  concourse_verify_ssl:bool=False,
  concourse_url:str=None,
  concourse_proxy_url:str=None,
  concourse_user:str='kubernetes',
  concourse_passwd:str='kubernetes',
  concourse_team:str='kubernetes',
  concourse_pipelines:[str]=None
):
    pullrequest_resources = _list_github_resources(
      concourse_url=concourse_url,
      concourse_user=concourse_user,
      concourse_passwd=concourse_passwd,
      concourse_team=concourse_team,
      concourse_pipelines=concourse_pipelines,
      github_url=github_url,
    )
    github_obj = _create_github_api_object(
          github_url=github_url,
          github_auth_token=github_auth_token,
          github_verify_ssl=github_verify_ssl
    )

    webhook_syncer = github.GithubWebHookSyncer(github_obj)
    failed_hooks = 0

    for res in pullrequest_resources:
        try:
            _sync_webhook(
              res=res,
              webhook_syncer=webhook_syncer,
              concourse_proxy_url=concourse_proxy_url,
              skip_ssl_validation=not concourse_verify_ssl
            )
        except RuntimeError as rte:
            failed_hooks += 1
            info(str(rte))

    if failed_hooks is not 0:
        fail('{n} webhooks could not be updated or created!'.format(n=failed_hooks))


def _sync_webhook(
  res:concourse.Resource,
  webhook_syncer:github.GithubWebHookSyncer,
  concourse_proxy_url: str,
  skip_ssl_validation: bool=False
):
    pipeline = res.pipeline
    # construct webhook endpoint
    routes = copy(pipeline.concourse_api.routes)
    # workaround: direct webhooks against delaying proxy
    routes.base_url = concourse_proxy_url

    github_src = res.github_source()

    repository = github_src.parse_repository()
    organisation = github_src.parse_organisation()
    webhook_url = routes.resource_check_webhook(
      pipeline_name=pipeline.name,
      resource_name=res.name,
      webhook_token=res.webhook_token()
    )

    webhook_syncer.add_or_update_hook(
      owner=organisation,
      repository_name=repository,
      callback_url=webhook_url,
      skip_ssl_validation=skip_ssl_validation
    )
    info('updated hook for: {o}/{r}'.format(o=organisation, r=repository))


def diff_pipelines(left_file: CliHints.yaml_file(), right_file: CliHints.yaml_file()):
    from deepdiff import DeepDiff
    from pprint import pprint

    diff = DeepDiff(left_file, right_file, ignore_order=True)
    if diff:
        pprint(diff)
        fail('diffs were found')
    else:
        info('the yaml documents are equivalent')
