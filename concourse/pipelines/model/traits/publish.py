from util import ensure_not_none
from model import NamedModelElement

from concourse.pipelines.modelbase import (
  PipelineStep,
  Trait,
  TraitTransformer,
  ModelValidationError,
  normalise_to_dict,
)

class PublishDockerImageDescriptor(NamedModelElement):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not 'inputs' in self.raw:
            self.raw['inputs'] = {}

    def input_repos(self):
        return self.raw['inputs'].get('repos', None) # None -> default to main_repository

    def input_steps(self):
        return self.raw['inputs'].get('steps', [])

    def registry_name(self):
        return self.raw['registry']

    def image_reference(self):
        return self.raw['image']

    def dockerfile_relpath(self):
        return self.raw.get('dockerfile', 'Dockerfile')

    def builddir_relpath(self):
        return self.raw.get('dir', None)

    def resource_name(self):
        parts = self.image_reference().split('/')
        # image references are lengthy (e.g. gcr.eu/<org>/<path>/../<name>)
        # -> shorten this a bit (keep domain and last part of url path)
        domain = parts[0]
        image_name = parts[-1]
        return '_'.join([domain, image_name])


class PublishTrait(Trait):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if not 'dockerimages' in self.raw:
            raise ModelValidationError('missing required attribute "dockerimages"')

    def dockerimages(self):
        return [
            PublishDockerImageDescriptor(name, args)
            for name, args
            in self.raw['dockerimages'].items()
        ]

    def transformer(self):
        return PublishTraitTransformer(trait=self, name=self.name)


class PublishTraitTransformer(TraitTransformer):
    def __init__(self, trait: PublishTrait, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.trait = ensure_not_none(trait)

    def inject_steps(self):
        # 'publish' step
        publish_step = PipelineStep(name='publish', raw_dict={}, is_synthetic=True)

        # 'prepare' step
        prepare_step = PipelineStep(name='prepare', raw_dict={}, is_synthetic=True)

        publish_step._add_dependency(prepare_step)

        yield prepare_step
        yield publish_step

    def process_pipeline_args(self, pipeline_args: 'PipelineArgs'):
        main_repo = pipeline_args.main_repository()
        prepare_step = pipeline_args.step('prepare')
        publish_step = pipeline_args.step('publish')

        image_name = main_repo.branch() + '-image'
        tag_name = main_repo.branch() + '-tag'

        # configure prepare step's outputs (consumed by publish step)
        prepare_step.add_output('image_path', image_name)
        prepare_step.add_output('tag_path', tag_name)

        # configure publish step's inputs (produced by prepare step)
        publish_step.add_input('image_path', image_name)
        publish_step.add_input('tag_path', tag_name)

        input_step_names = set()
        for image_descriptor in self.trait.dockerimages():
            # todo: image-specific prepare steps
            input_step_names.update(image_descriptor.input_steps())

        for input_step_name in input_step_names:
            input_step = pipeline_args.step(input_step_name)
            input_name = input_step.output_dir()
            prepare_step.add_input(input_name, input_name)


        # prepare-step depdends on every other step, except publish and release
        # TODO: do not hard-code knowledge about 'release' step
        for step in pipeline_args.steps():
            if step.name in ['publish', 'release']:
                continue
            prepare_step._add_dependency(step)

